#!/usr/bin/env python3
"""
Missing Attachments Extractor

This script reads the original text content from the financial_analysis.db database
from records where amount_increase > 0, and uses Ollama LLM via LangChain to identify
missing attachments referenced in the email/message content. Results are stored in a
new table in the same database, with separate records for each missing attachment.
"""

import os
import sqlite3
import argparse
import logging
import json
from typing import Optional, Dict, Any, List

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


def extract_missing_attachments(text: str, llm) -> Dict[str, Any]:
    """Use LLM to extract missing attachments and message date from text."""
    prompt_template = """You are analyzing an email or message thread to identify missing attachments that were referenced but not included.

Analyze the following text content and identify:
- Any attachments that are mentioned or referenced but are missing or not included
- The date and time when the message(s) were sent (extract from email headers like From, Date, Sent, etc.)

Look for phrases like:
- "Please see attached"
- "I've attached"
- "See attachment"
- References to files that should be attached but aren't present in either the subject line of the email or the body of the email.
- Any mention of documents, files, or attachments that are expected but missing

Return your analysis as a JSON object with the following structure:
{{
    "message_date": "Extract the date and time from the email thread. Format as YYYY-MM-DD HH:MM:SS if available, or YYYY-MM-DD if only date is available, or the best approximation from email headers. If no date/time can be determined, use 'Unknown'",
    "missing_attachments": ["List of attachment filenames that are referenced but missing. Each attachment should be a separate string in the array. If no missing attachments are found, use an empty array []"]
}}

IMPORTANT:
- Return ONLY valid JSON, no other text
- Extract the date and time from email headers (From, Date, Sent, etc.) - look for the earliest or most relevant date in the thread
- Use ISO format for dates (YYYY-MM-DD) and include time if available (YYYY-MM-DD HH:MM:SS)
- If multiple attachments are mentioned, include each one as a separate string in the array
- Only include attachments that are explicitly mentioned as missing or referenced but not present
- If an attachment is mentioned but you cannot determine if it's missing, do not include it
- CRITICAL: Each attachment name MUST be an actual filename with a file extension. The filename should include a dot (.) followed by typically 3 characters (e.g., .pdf, .doc, .xlsx, .xls, .docx, .txt, .jpg, .png, etc.). Extract the exact filename as mentioned in the email, including the extension. Do not use generic descriptions like "the invoice" or "the contract" - use the actual filename like "invoice_2024.pdf" or "contract.docx". If only a generic description is mentioned without a filename, try to infer a reasonable filename with an appropriate extension based on the context, but prefer exact filenames when available.

This is an email thread, so multiple emails may be included:
{text}"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an email attachment analyzer. Always respond with valid JSON only. Extract actual filenames with extensions (e.g., document.pdf, report.xlsx) - not generic descriptions."),
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
        message_date = str(parsed.get("message_date", "Unknown"))
        missing_attachments = parsed.get("missing_attachments", [])
        
        # Ensure missing_attachments is a list
        if not isinstance(missing_attachments, list):
            if isinstance(missing_attachments, str) and missing_attachments:
                missing_attachments = [missing_attachments]
            else:
                missing_attachments = []
        
        # Filter out empty strings
        missing_attachments = [str(att).strip() for att in missing_attachments if att and str(att).strip()]
        
        result_dict = {
            "message_date": message_date,
            "missing_attachments": missing_attachments
        }
        
        return result_dict
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from LLM response: {e}")
        logger.error(f"LLM response was: {result[:500] if 'result' in locals() else 'N/A'}...")
        return {
            "message_date": "Unknown",
            "missing_attachments": []
        }
    except Exception as e:
        logger.error(f"Error analyzing text with LLM: {e}")
        return {
            "message_date": "Unknown",
            "missing_attachments": []
        }


def init_missing_attachments_table(db_path: str) -> None:
    """Initialize the missing_attachments table in the database."""
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
    
    # Create missing_attachments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS missing_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_analysis_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            attachment_name TEXT NOT NULL,
            message_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pdf_analysis_id) REFERENCES pdf_analysis(id) ON DELETE CASCADE
        )
    ''')
    
    # Create indexes for better query performance
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_missing_attachments_pdf_analysis_id 
        ON missing_attachments(pdf_analysis_id)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_missing_attachments_filename 
        ON missing_attachments(filename)
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Missing attachments table initialized")


def get_records_with_amount_increase(db_path: str, skip_existing: bool = True) -> list:
    """Get records from pdf_analysis where amount_increase > 0."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if skip_existing:
        # Get records with amount_increase > 0 that don't have corresponding missing_attachments entries
        cursor.execute('''
            SELECT pa.id, pa.filename, pa.original
            FROM pdf_analysis pa
            LEFT JOIN missing_attachments ma ON pa.id = ma.pdf_analysis_id
            WHERE pa.amount_increase > 0
            AND ma.id IS NULL
            ORDER BY pa.id
        ''')
    else:
        # Get all records with amount_increase > 0
        cursor.execute('''
            SELECT id, filename, original
            FROM pdf_analysis
            WHERE amount_increase > 0
            ORDER BY id
        ''')
    
    records = cursor.fetchall()
    conn.close()
    return records


def process_record(record_id: int, filename: str, original_text: str, llm, db_path: str) -> bool:
    """Process a single record and store missing attachments in database."""
    logger.info(f"Analyzing record {record_id} ({filename}) for missing attachments...")
    
    if not original_text or original_text.strip() == "[No text could be extracted from this PDF]":
        logger.warning(f"Skipping record {record_id} - no text content available")
        return False
    
    # Extract missing attachments with LLM
    analysis = extract_missing_attachments(original_text, llm)
    
    # If no missing attachments found, skip
    if not analysis["missing_attachments"]:
        logger.info(f"No missing attachments found in record {record_id}")
        return False
    
    # Store in database - create one record per attachment
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Delete existing records for this pdf_analysis_id (for re-processing)
    cursor.execute("DELETE FROM missing_attachments WHERE pdf_analysis_id = ?", (record_id,))
    
    # Insert one record per missing attachment
    message_date = analysis["message_date"]
    inserted_count = 0
    
    for attachment_name in analysis["missing_attachments"]:
        cursor.execute('''
            INSERT INTO missing_attachments (pdf_analysis_id, filename, attachment_name, message_date)
            VALUES (?, ?, ?, ?)
        ''', (record_id, filename, attachment_name, message_date))
        inserted_count += 1
    
    conn.commit()
    conn.close()
    
    logger.info(f"Created {inserted_count} missing attachment record(s) for record {record_id} - Date: {message_date}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Extract missing attachments from PDF content where amount_increase > 0 using Ollama LLM',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Extract missing attachments from all unprocessed records
  python extract_missing_attachments.py --db financial_analysis.db

  # Use a specific Ollama model
  python extract_missing_attachments.py --db financial_analysis.db --model llama3.2

  # Re-process all records (including already processed ones)
  python extract_missing_attachments.py --db financial_analysis.db --no-skip-existing

  # Process only a limited number of records (for testing)
  python extract_missing_attachments.py --db financial_analysis.db --limit 10
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
        help='Skip records that are already processed (default: True)'
    )
    
    parser.add_argument(
        '--no-skip-existing',
        action='store_false',
        dest='skip_existing',
        help='Process all records even if already processed'
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
    
    # Initialize missing attachments table
    try:
        init_missing_attachments_table(args.db)
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
    logger.info(f"Querying database for records with amount_increase > 0...")
    records = get_records_with_amount_increase(args.db, args.skip_existing)
    
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
    skipped = 0
    
    for record_id, filename, original_text in records:
        try:
            result = process_record(record_id, filename, original_text, llm, args.db)
            if result:
                processed += 1
            else:
                skipped += 1
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
            break
        except Exception as e:
            logger.error(f"Error processing record {record_id} ({filename}): {e}")
            failed += 1
            continue
    
    logger.info(f"\nProcessing complete!")
    logger.info(f"  Processed: {processed}")
    logger.info(f"  Skipped (no missing attachments): {skipped}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Database: {args.db}")
    
    return 0


if __name__ == '__main__':
    exit(main())

