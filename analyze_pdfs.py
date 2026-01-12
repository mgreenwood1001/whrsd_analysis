#!/usr/bin/env python3
"""
PDF Accounting Gap Analyzer

This script processes PDF documents (typically emails), extracts text content, and uses Ollama LLM
via LangChain to identify accounting gaps where monetary amounts changed beyond what was originally
thought was owed. Results are stored in a SQLite database with separate columns for title, 
description, and amount increase.
"""

import os
import sqlite3
import argparse
from pathlib import Path
from typing import Optional, Dict, Any
import logging
import json

# PDF processing
try:
    import pypdf
except ImportError:
    import PyPDF2 as pypdf

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


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text content from a PDF file."""
    try:
        text_content = []
        with open(pdf_path, 'rb') as file:
            pdf_reader = pypdf.PdfReader(file)
            for page_num, page in enumerate(pdf_reader.pages, 1):
                try:
                    page_text = page.extract_text()
                    if page_text.strip():
                        text_content.append(page_text)
                except Exception as e:
                    logger.warning(f"Error extracting text from page {page_num} of {pdf_path}: {e}")
                    continue
        
        return "\n\n".join(text_content)
    except Exception as e:
        logger.error(f"Error reading PDF {pdf_path}: {e}")
        return ""


def analyze_financial_content(text: str, llm) -> Dict[str, Any]:
    """Use LLM to analyze text and identify accounting gaps/discrepancies."""
    prompt_template = """You are a financial auditor analyzing documents for accounting discrepancies. 
Look for situations where the town/district thought a monetary amount was one figure, but the figure changed or increased beyond what was originally thought was owed.

Analyze the following text and identify any accounting gaps or discrepancies where:
- An initial monetary amount was stated or expected
- The amount changed or increased beyond the original expectation
- There is a difference between what was originally thought/budgeted and what actually occurred

Return your analysis as a JSON object with the following structure:
{{
    "title": "A one-sentence description of the discrepancy (or 'No accounting discrepancy found' if none)",
    "description": "A detailed summary of the discrepancy, including what amount was originally thought/expected and what it changed to. If no discrepancy, state 'No accounting discrepancy or financial impact found.'",
    "item": "The item, service, or line item that the adjustment was for (e.g., 'Building maintenance contract', 'Utility expenses', 'Software licensing'). If no discrepancy, use 'N/A'",
    "participants": "A comma-separated list of names of people involved in the communication (e.g., 'John Smith, Jane Doe'). Extract names from email headers (From, To, CC) and signatures. If no names found, use 'Unknown'",
    "amount_increase": "The dollar amount that represents the increase beyond what was originally thought (as a number without $ sign, e.g., 5000.00). If no discrepancy, use 0.00"
}}

IMPORTANT: 
- Return ONLY valid JSON, no other text
- If there is no discrepancy or no financial impact, set amount_increase to 0.00
- Extract the actual numerical increase amount if a discrepancy exists
- The amount_increase should be the difference between the original expected amount and the new/changed amount

Text to analyze:
{text}"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a financial auditor. Always respond with valid JSON only."),
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
            "title": str(parsed.get("title", "No accounting discrepancy found")),
            "description": str(parsed.get("description", "No accounting discrepancy or financial impact found.")),
            "item": str(parsed.get("item", "N/A")),
            "participants": str(parsed.get("participants", "Unknown")),
            "amount_increase": float(parsed.get("amount_increase", 0.0))
        }
        
        return result_dict
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from LLM response: {e}")
        logger.error(f"LLM response was: {result[:500] if 'result' in locals() else 'N/A'}...")
        return {
            "title": "Error parsing LLM response",
            "description": f"Failed to parse JSON response: {str(e)}",
            "item": "N/A",
            "participants": "Unknown",
            "amount_increase": 0.0
        }
    except Exception as e:
        logger.error(f"Error analyzing text with LLM: {e}")
        return {
            "title": "Error during analysis",
            "description": f"Error during analysis: {str(e)}",
            "item": "N/A",
            "participants": "Unknown",
            "amount_increase": 0.0
        }


def init_database(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database with the required schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pdf_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            item TEXT NOT NULL,
            participants TEXT NOT NULL,
            amount_increase REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    return conn


def process_pdf(pdf_path: str, llm, conn: sqlite3.Connection, skip_existing: bool = True) -> bool:
    """Process a single PDF file and store results in database."""
    filename = os.path.basename(pdf_path)
    
    # Check if already processed
    if skip_existing:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM pdf_analysis WHERE filename = ?", (filename,))
        if cursor.fetchone():
            logger.info(f"Skipping {filename} - already in database")
            return True
    
    logger.info(f"Processing {filename}...")
    
    # Extract text
    text_content = extract_text_from_pdf(pdf_path)
    
    if not text_content.strip():
        logger.warning(f"No text extracted from {filename}")
        text_content = "[No text could be extracted from this PDF]"
    
    # Analyze with LLM
    logger.info(f"Analyzing {filename} with LLM...")
    analysis = analyze_financial_content(text_content, llm)
    
    # Store in database
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pdf_analysis (filename, original, title, description, item, participants, amount_increase)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        filename, 
        text_content, 
        analysis["title"],
        analysis["description"],
        analysis["item"],
        analysis["participants"],
        analysis["amount_increase"]
    ))
    conn.commit()
    
    logger.info(f"Completed processing {filename} - Amount increase: ${analysis['amount_increase']:.2f}")
    return True


def find_pdf_files(directory: str) -> list:
    """Find all PDF files in a directory recursively."""
    pdf_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))
    return sorted(pdf_files)


def main():
    parser = argparse.ArgumentParser(
        description='Analyze PDF files for accounting gaps/discrepancies using Ollama LLM',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Process all PDFs in the pdfs directory
  python analyze_pdfs.py --pdf-dir pdfs/whrsd-transparency.org/pdfs --db financial_analysis.db

  # Use a specific Ollama model
  python analyze_pdfs.py --pdf-dir pdfs --db financial_analysis.db --model llama3.2

  # Process only new PDFs (skip existing)
  python analyze_pdfs.py --pdf-dir pdfs --db financial_analysis.db --skip-existing

  # Process all PDFs including already processed ones
  python analyze_pdfs.py --pdf-dir pdfs --db financial_analysis.db --no-skip-existing
        '''
    )
    
    parser.add_argument(
        '--pdf-dir',
        type=str,
        default='pdfs',
        help='Directory containing PDF files (default: pdfs)'
    )
    
    parser.add_argument(
        '--db',
        type=str,
        default='accounting_gaps.db',
        help='SQLite database file path (default: accounting_gaps.db)'
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
        help='Skip PDFs that are already in the database (default: True)'
    )
    
    parser.add_argument(
        '--no-skip-existing',
        action='store_false',
        dest='skip_existing',
        help='Process all PDFs even if already in database'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit the number of PDFs to process (useful for testing)'
    )
    
    args = parser.parse_args()
    
    # Validate PDF directory
    if not os.path.isdir(args.pdf_dir):
        logger.error(f"PDF directory does not exist: {args.pdf_dir}")
        return 1
    
    # Initialize database
    logger.info(f"Initializing database: {args.db}")
    conn = init_database(args.db)
    
    # Initialize LLM
    logger.info(f"Initializing Ollama LLM with model: {args.model}")
    try:
        llm = ChatOllama(model=args.model, temperature=0)
    except Exception as e:
        logger.error(f"Failed to initialize Ollama LLM. Make sure Ollama is running and the model '{args.model}' is available.")
        logger.error(f"Error: {e}")
        logger.error("You can install/run Ollama at https://ollama.ai")
        return 1
    
    # Find PDF files
    logger.info(f"Searching for PDF files in: {args.pdf_dir}")
    pdf_files = find_pdf_files(args.pdf_dir)
    
    if not pdf_files:
        logger.warning(f"No PDF files found in {args.pdf_dir}")
        return 1
    
    logger.info(f"Found {len(pdf_files)} PDF file(s)")
    
    if args.limit:
        pdf_files = pdf_files[:args.limit]
        logger.info(f"Limited to processing {len(pdf_files)} PDF file(s)")
    
    # Process each PDF
    processed = 0
    failed = 0
    
    for pdf_path in pdf_files:
        try:
            process_pdf(pdf_path, llm, conn, args.skip_existing)
            processed += 1
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
            break
        except Exception as e:
            logger.error(f"Error processing {pdf_path}: {e}")
            failed += 1
            continue
    
    conn.close()
    
    logger.info(f"\nProcessing complete!")
    logger.info(f"  Processed: {processed}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Database: {args.db}")
    
    return 0


if __name__ == '__main__':
    exit(main())

