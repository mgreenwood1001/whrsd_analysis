#!/usr/bin/env python3
"""
PDF Alarm and Discrepancy Analyzer

This script reads the original text content from the financial_analysis.db database
and uses Ollama LLM via LangChain to identify questionable actions, discrepancies,
or subjects that raise alarms. Results are stored in a new table in the same database.
"""

import os
import sqlite3
import argparse
import logging
import json
from typing import Optional, Dict, Any

# LangChain and Ollama
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_for_alarms(text: str, llm) -> Dict[str, Any]:
    """Use LLM to analyze text for questionable actions, discrepancies, or alarm-raising subjects."""
    prompt_template = """You are a Town/District compliance auditor analyzing documents for potential issues.
You are responsible for ensuring that the Town/District is compliant with all applicable laws and regulations.
You are also responsible for ensuring that the Town/District is operating in a transparent and ethical manner.
You can ignore minor discrepancies that are not significant or that are not relevant to the Town/District's compliance, email signatures, etc.

Analyze the following text content (typically an email or communication) and identify:
- Questionable actions or decisions
- Discrepancies or inconsistencies
- Subjects or topics that raise alarms or red flags
- Potential ethical or procedural violations
- Unusual patterns or behaviors
- Conflicts of interest
- Any other concerns that warrant attention

Return your analysis as a JSON object with the following structure:
{{
    "date_time": "Extract the date and time from the email thread. Format as YYYY-MM-DD HH:MM:SS if available, or YYYY-MM-DD if only date is available, or the best approximation from email headers. If no date/time can be determined, use 'Unknown'",
    "summary": "A comprehensive summary of your findings. Be specific and cite examples from the text where possible. Use plain text only - no ASCII art, no special formatting, just simple readable text. If no concerning issues are found, state that clearly."
}}

IMPORTANT:
- Return ONLY valid JSON, no other text
- Do not use ASCII art, decorative characters, or special formatting in the summary - use plain text only
- Extract the date and time from email headers (From, Date, Sent, etc.) - look for the earliest or most relevant date in the thread
- Use ISO format for dates (YYYY-MM-DD) and include time if available (YYYY-MM-DD HH:MM:SS)

This is an email thread, so multiple emails may be included:
{text}"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a Town/District compliance auditor. Always respond with valid JSON only. Use plain text, no ASCII art or special formatting."),
        ("user", prompt_template)
    ])
    
    chain = prompt | llm | StrOutputParser()
    
    try:
        # Truncate text if it's too long (to avoid token limits)
        max_chars = 8000
        if len(text) > max_chars:
            text_to_analyze = text[:max_chars] + "\n\n[... text truncated ...]"
            logger.warning(f"Text truncated to {max_chars} characters for analysis")
        else:
            text_to_analyze = text
        
        result = chain.invoke({"text": text_to_analyze})
        
        # Parse JSON from the result
        # Sometimes LLMs add markdown code blocks, so we need to extract JSON
        json_str = result.strip()
        
        # Remove markdown code blocks if present
        if json_str.startswith("```json"):
            json_str = json_str[7:]  # Remove ```json
        elif json_str.startswith("```"):
            json_str = json_str[3:]  # Remove ```
        if json_str.endswith("```"):
            json_str = json_str[:-3]  # Remove closing ```
        json_str = json_str.strip()
        
        # Parse JSON
        parsed = json.loads(json_str)
        
        # Validate and normalize the result
        result_dict = {
            "date_time": str(parsed.get("date_time", "Unknown")),
            "summary": str(parsed.get("summary", "No analysis available."))
        }
        
        return result_dict
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from LLM response: {e}")
        logger.error(f"LLM response was: {result[:500] if 'result' in locals() else 'N/A'}...")
        return {
            "date_time": "Unknown",
            "summary": f"Error parsing LLM response: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error analyzing text with LLM: {e}")
        return {
            "date_time": "Unknown",
            "summary": f"Error during analysis: {str(e)}"
        }


def init_alarm_table(db_path: str) -> None:
    """Initialize the alarm_analysis table in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if pdf_analysis table exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='pdf_analysis'
    """)
    if not cursor.fetchone():
        logger.error(f"Error: pdf_analysis table not found in {db_path}")
        logger.error("Please run analyze_pdfs.py first to create the database and initial table.")
        conn.close()
        raise ValueError("pdf_analysis table not found")
    
    # Create alarm_analysis table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alarm_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_analysis_id INTEGER NOT NULL,
            date_time TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pdf_analysis_id) REFERENCES pdf_analysis(id) ON DELETE CASCADE
        )
    ''')
    
    # If table exists with old schema, migrate it
    cursor.execute("PRAGMA table_info(alarm_analysis)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'alarm_summary' in columns and 'summary' not in columns:
        logger.info("Migrating alarm_analysis table to new schema...")
        cursor.execute('''
            ALTER TABLE alarm_analysis 
            ADD COLUMN summary TEXT
        ''')
        cursor.execute('''
            ALTER TABLE alarm_analysis 
            ADD COLUMN date_time TEXT DEFAULT 'Unknown'
        ''')
        cursor.execute('''
            UPDATE alarm_analysis 
            SET summary = alarm_summary 
            WHERE summary IS NULL
        ''')
        # Note: SQLite doesn't support dropping columns easily, so we leave alarm_summary
        # but the new code will use summary
        conn.commit()
    
    # Create index on foreign key for better query performance
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_alarm_pdf_analysis_id 
        ON alarm_analysis(pdf_analysis_id)
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Alarm analysis table initialized")


def get_unprocessed_records(db_path: str, skip_existing: bool = True) -> list:
    """Get records from pdf_analysis that haven't been processed for alarms yet."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if skip_existing:
        # Get records that don't have corresponding alarm_analysis entries
        cursor.execute('''
            SELECT pa.id, pa.filename, pa.original
            FROM pdf_analysis pa
            LEFT JOIN alarm_analysis aa ON pa.id = aa.pdf_analysis_id
            WHERE aa.id IS NULL
            ORDER BY pa.id
        ''')
    else:
        # Get all records
        cursor.execute('''
            SELECT id, filename, original
            FROM pdf_analysis
            ORDER BY id
        ''')
    
    records = cursor.fetchall()
    conn.close()
    return records


def process_record(record_id: int, filename: str, original_text: str, llm, db_path: str) -> bool:
    """Process a single record and store alarm analysis in database."""
    logger.info(f"Analyzing record {record_id} ({filename}) for alarms...")
    
    if not original_text or original_text.strip() == "[No text could be extracted from this PDF]":
        logger.warning(f"Skipping record {record_id} - no text content available")
        return False
    
    # Analyze with LLM
    analysis = analyze_for_alarms(original_text, llm)
    
    # Store in database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if record already exists (for re-processing)
    cursor.execute("SELECT id FROM alarm_analysis WHERE pdf_analysis_id = ?", (record_id,))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing record
        cursor.execute('''
            UPDATE alarm_analysis 
            SET date_time = ?, summary = ?, created_at = CURRENT_TIMESTAMP
            WHERE pdf_analysis_id = ?
        ''', (analysis["date_time"], analysis["summary"], record_id))
        logger.info(f"Updated alarm analysis for record {record_id} - Date: {analysis['date_time']}")
    else:
        # Insert new record
        cursor.execute('''
            INSERT INTO alarm_analysis (pdf_analysis_id, date_time, summary)
            VALUES (?, ?, ?)
        ''', (record_id, analysis["date_time"], analysis["summary"]))
        logger.info(f"Created alarm analysis for record {record_id} - Date: {analysis['date_time']}")
    
    conn.commit()
    conn.close()
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Analyze PDF content for alarms, discrepancies, and questionable actions using Ollama LLM',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Analyze all unprocessed records in the database
  python analyze_alarms.py --db financial_analysis.db

  # Use a specific Ollama model
  python analyze_alarms.py --db financial_analysis.db --model gpt-oss:20b

  # Re-process all records (including already processed ones)
  python analyze_alarms.py --db financial_analysis.db --no-skip-existing

  # Process only a limited number of records (for testing)
  python analyze_alarms.py --db financial_analysis.db --limit 10
        '''
    )
    
    parser.add_argument(
        '--db',
        type=str,
        default='financial_analysis.db',
        help='SQLite database file path (default: financial_analysis.db)'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default='llama3.2',
        help='Ollama model to use (default: llama3.2)'
    )
    
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        default=True,
        help='Skip records that are already analyzed (default: True)'
    )
    
    parser.add_argument(
        '--no-skip-existing',
        action='store_false',
        dest='skip_existing',
        help='Process all records even if already analyzed'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit the number of records to process (useful for testing)'
    )
    
    args = parser.parse_args()
    
    # Validate database file
    if not os.path.isfile(args.db):
        logger.error(f"Database file does not exist: {args.db}")
        logger.error("Please run analyze_pdfs.py first to create the database.")
        return 1
    
    # Initialize alarm table
    try:
        init_alarm_table(args.db)
    except ValueError:
        return 1
    
    # Initialize LLM
    logger.info(f"Initializing Ollama LLM with model: {args.model}")
    try:
        llm = ChatOllama(model=args.model, temperature=0)
    except Exception as e:
        logger.error(f"Failed to initialize Ollama LLM. Make sure Ollama is running and the model '{args.model}' is available.")
        logger.error(f"Error: {e}")
        logger.error("You can install/run Ollama at https://ollama.ai")
        return 1
    
    # Get records to process
    logger.info(f"Querying database for records to process...")
    records = get_unprocessed_records(args.db, args.skip_existing)
    
    if not records:
        logger.info("No records to process.")
        return 0
    
    logger.info(f"Found {len(records)} record(s) to process")
    
    if args.limit:
        records = records[:args.limit]
        logger.info(f"Limited to processing {len(records)} record(s)")
    
    # Process each record
    processed = 0
    failed = 0
    
    for record_id, filename, original_text in records:
        try:
            process_record(record_id, filename, original_text, llm, args.db)
            processed += 1
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
            break
        except Exception as e:
            logger.error(f"Error processing record {record_id} ({filename}): {e}")
            failed += 1
            continue
    
    logger.info(f"\nProcessing complete!")
    logger.info(f"  Processed: {processed}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Database: {args.db}")
    
    return 0


if __name__ == '__main__':
    exit(main())

