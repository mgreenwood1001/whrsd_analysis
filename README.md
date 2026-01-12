# Whitman Hanson Regional School District Transparency

# Legal Disclaimer

**IMPORTANT**: This project and its analysis tools are provided for informational and analytical purposes only. The system is designed purely for the purpose of analyzing the data at hand. No claims to accuracy, completeness, or reliability of the analysis results are guaranteed. The AI-powered analysis may contain errors, misinterpretations, or false positives. Users should independently verify any findings and should not rely solely on the automated analysis for making decisions or drawing conclusions. The authors and contributors of this project make no warranties, express or implied, regarding the accuracy, reliability, or suitability of the analysis for any particular purpose. Use of this system and its outputs is at your own risk.

## Inputs: Whitman Transparency Google Admin Extract from the District

https://whrsd-transparency.org/

## Output Data

A link to the output analysis is here:
https://docs.google.com/spreadsheets/d/14OkLoNyUvtcC-osBgt7EOTo-Rph4-NpYYER-d-Tjxhw/edit?usp=sharing

## Overview

This project provides a comprehensive financial analysis and compliance auditing system for processing and analyzing Town/District communications, specifically designed to examine documents from WHRSD (Whitman Hanson Regional School District) transparency records obtained via the link above. The system uses advanced AI-powered text analysis to automatically identify financial discrepancies, compliance issues, and missing documentation in email communications and PDF documents.  LLM models that execute against this content are done in a local machine sandboxed environment, not cloud based.

### What This Project Does

The system processes PDF documents (primarily email communications) through a multi-stage analysis pipeline that:

1. **Extracts and Analyzes Financial Information**: The first stage processes PDF files to extract text content and uses Large Language Models (LLMs) to identify accounting gaps and financial discrepancies. This includes detecting situations where monetary amounts changed beyond what was originally expected, budgeted, or communicated, helping to uncover potential cost overruns, budget variances, or unexpected financial adjustments.

2. **Identifies Compliance and Ethical Concerns**: The second stage performs a comprehensive compliance audit on all processed documents, analyzing content from a regulatory and ethical perspective. It flags questionable actions, procedural violations, conflicts of interest, unusual patterns, and other red flags that may indicate non-compliance with laws, regulations, or ethical standards.

3. **Tracks Missing Documentation**: The third stage focuses specifically on records with identified financial discrepancies, extracting information about missing attachments that were referenced in communications but not included. This helps identify gaps in documentation that may be critical for understanding financial transactions or compliance matters.

### Key Features

- **Automated Document Processing**: Recursively scans directories of PDF files and processes them in batch
- **AI-Powered Analysis**: Uses locally-run LLM models (via Ollama) to perform intelligent text analysis without sending data to external services
- **Structured Data Storage**: All analysis results are stored in a SQLite database with proper relational structure, indexes, and foreign key constraints
- **Comprehensive Tracking**: Tracks financial amounts, participants, dates, compliance issues, and missing documentation
- **Idempotent Operations**: Scripts can be safely re-run without duplicating data
- **Privacy-Focused**: All processing happens locally using open-source models, ensuring sensitive government communications remain private

### Technology Stack

The project leverages **Ollama LLM** via **LangChain** for intelligent text analysis, storing results in a **SQLite database** (`financial_analysis.db`). The system is designed to work with locally-hosted models (such as `gpt-oss:20b` or `llama3.2`), ensuring that sensitive government communications are processed entirely on-premises without being sent to external cloud services. This approach provides both privacy and control over the analysis process.

### Use Cases

This system is particularly valuable for:
- **Financial Auditors**: Identifying budget variances and unexpected cost increases
- **Compliance Officers**: Detecting potential regulatory violations and ethical concerns
- **Transparency Advocates**: Analyzing public records for accountability
- **Investigative Journalists**: Uncovering patterns and discrepancies in government communications
- **Citizen Oversight**: Enabling public scrutiny of government financial practices

The automated nature of the system allows for processing large volumes of documents efficiently, while the AI-powered analysis helps surface issues that might be missed in manual review. 

## Setup

### Prerequisites

- **Python 3.x** (Python 3.8 or higher recommended)
- **pip** (Python package installer)
- **Ollama** (for running LLM models locally)

### Installation Steps

1. **Verify Python Installation**

   Check if Python is installed and verify the version:
   ```bash
   python --version
   # or
   python3 --version
   ```

   If Python is not installed, download it from [python.org](https://www.python.org/downloads/).

2. **Create a Virtual Environment (Recommended)**

   Create an isolated Python environment to avoid conflicts with system packages:
   ```bash
   python -m venv venv
   # or
   python3 -m venv venv
   ```

   Activate the virtual environment:
   - **On macOS/Linux:**
     ```bash
     source venv/bin/activate
     ```
   - **On Windows:**
     ```bash
     venv\Scripts\activate
     ```

3. **Install Python Dependencies**

   Install all required packages from `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```

   This will install:
   - `pypdf` - For PDF text extraction
   - `langchain` - LLM framework
   - `langchain-ollama` - Ollama integration
   - `langchain-core` - Core LangChain components

4. **Install and Setup Ollama**

   Ollama is required to run the LLM models locally. Install it from [ollama.ai](https://ollama.ai).

   After installation, download a model (the scripts default to `llama3.2`, but you can use others like `gpt-oss:20b`):
   ```bash
   ollama pull llama3.2
   # or for a larger model
   ollama pull gpt-oss:20b
   ```

   Make sure Ollama is running before executing the scripts:
   ```bash
   ollama serve
   ```

### Verification

Verify the setup by checking that all packages are installed:
```bash
pip list
```

You should see `pypdf`, `langchain`, `langchain-ollama`, and `langchain-core` in the list.


## Scripts

### 1. `analyze_pdfs.py` - PDF Accounting Gap Analyzer

**Purpose**: Initial processing script that extracts text from PDF files and identifies accounting gaps where monetary amounts changed beyond what was originally expected.

**What it does**:
- Scans a directory for PDF files (recursively)
- Extracts text content from each PDF
- Uses LLM to analyze the content for accounting discrepancies
- Identifies situations where:
  - An initial monetary amount was stated or expected
  - The amount changed or increased beyond the original expectation
  - There is a difference between what was originally thought/budgeted and what actually occurred

**Output**: Creates the `pdf_analysis` table in the database with:
- `id` - Primary key
- `filename` - Name of the PDF file
- `original` - Full extracted text content
- `title` - One-sentence description of the discrepancy
- `description` - Detailed summary of the discrepancy
- `item` - The item/service/line item that the adjustment was for
- `participants` - Comma-separated list of people involved
- `amount_increase` - Dollar amount of the increase (0.00 if no discrepancy)
- `created_at` - Timestamp

**Usage**:
```bash
# Process all PDFs in a directory
python analyze_pdfs.py --pdf-dir pdfs/whrsd-transparency.org/pdfs --db financial_analysis.db

# Use a specific Ollama model
python analyze_pdfs.py --pdf-dir pdfs --db financial_analysis.db --model llama3.2

# Process only new PDFs (skip existing)
python analyze_pdfs.py --pdf-dir pdfs --db financial_analysis.db --skip-existing

# Process all PDFs including already processed ones
python analyze_pdfs.py --pdf-dir pdfs --db financial_analysis.db --no-skip-existing

# Limit processing for testing
python analyze_pdfs.py --pdf-dir pdfs --db financial_analysis.db --limit 10
```

---

### 2. `analyze_alarms.py` - PDF Alarm and Discrepancy Analyzer

**Purpose**: Analyzes all records in the `pdf_analysis` table to identify questionable actions, discrepancies, or subjects that raise compliance alarms.

**What it does**:
- Reads original text content from the `pdf_analysis` table
- Uses LLM to analyze content from a compliance auditor perspective
- Identifies:
  - Questionable actions or decisions
  - Discrepancies or inconsistencies
  - Subjects or topics that raise alarms or red flags
  - Potential ethical or procedural violations
  - Unusual patterns or behaviors
  - Conflicts of interest
  - Any other concerns that warrant attention

**Output**: Creates the `alarm_analysis` table with:
- `id` - Primary key
- `pdf_analysis_id` - Foreign key to `pdf_analysis` table
- `date_time` - Date and time extracted from email headers
- `summary` - Comprehensive summary of findings
- `created_at` - Timestamp

**Usage**:
```bash
# Analyze all unprocessed records
python analyze_alarms.py --db financial_analysis.db

# Use a specific Ollama model
python analyze_alarms.py --db financial_analysis.db --model llama3.2

# Re-process all records (including already processed ones)
python analyze_alarms.py --db financial_analysis.db --no-skip-existing

# Process only a limited number of records (for testing)
python analyze_alarms.py --db financial_analysis.db --limit 10
```

---

### 3. `extract_missing_attachments.py` - Missing Attachments Extractor

**Purpose**: Extracts information about missing attachments from records where `amount_increase > 0`, identifying files that were referenced but not included in the email.

**What it does**:
- Queries `pdf_analysis` table for records where `amount_increase > 0`
- Uses LLM to analyze the original text content
- Identifies missing attachments by looking for phrases like:
  - "Please see attached"
  - "I've attached"
  - "See attachment"
  - References to files that should be attached but aren't present
- Extracts actual filenames with extensions (e.g., `invoice_2024.pdf`, `contract.docx`)
- Extracts the date when the message(s) were sent

**Output**: Creates the `missing_attachments` table with:
- `id` - Primary key
- `pdf_analysis_id` - Foreign key to `pdf_analysis` table
- `filename` - Name of the PDF file that referenced the missing attachment
- `attachment_name` - Name of the missing attachment file (with extension)
- `message_date` - Date and time when the message was sent
- `created_at` - Timestamp

**Note**: If multiple attachments are missing, separate records are created for each attachment with the same `filename` and `message_date`.

**Usage**:
```bash
# Extract missing attachments from all unprocessed records
python extract_missing_attachments.py --db financial_analysis.db

# Use a specific Ollama model
python extract_missing_attachments.py --db financial_analysis.db --model llama3.2

# Re-process all records (including already processed ones)
python extract_missing_attachments.py --db financial_analysis.db --no-skip-existing

# Process only a limited number of records (for testing)
python extract_missing_attachments.py --db financial_analysis.db --limit 10
```

---

## Workflow

The typical workflow for using these scripts is:

1. **First**: Run `analyze_pdfs.py` to process PDF files and populate the `pdf_analysis` table
2. **Second**: Run `analyze_alarms.py` to analyze all records for compliance concerns
3. **Third**: Run `extract_missing_attachments.py` to identify missing attachments in records with financial discrepancies

## Database Schema

### `pdf_analysis` table
- Primary table created by `analyze_pdfs.py`
- Contains extracted text and financial analysis results
- Referenced by both `alarm_analysis` and `missing_attachments` tables

### `alarm_analysis` table
- Created by `analyze_alarms.py`
- Links to `pdf_analysis` via foreign key
- Contains compliance and alarm analysis

### `missing_attachments` table
- Created by `extract_missing_attachments.py`
- Links to `pdf_analysis` via foreign key
- Contains missing attachment information for records with `amount_increase > 0`
- Multiple records per PDF if multiple attachments are missing

## Dependencies

All scripts require:
- Python 3.x
- `pypdf` (or `PyPDF2`) - For PDF text extraction
- `langchain` - LLM framework
- `langchain-ollama` - Ollama integration
- `langchain-core` - Core LangChain components
- **Ollama** - Must be running locally with a model installed (default: `llama3.2`)

Install dependencies:
```bash
pip install -r requirements.txt
```

## Common Options

All scripts support:
- `--db` - Database file path (default: `financial_analysis.db`)
- `--model` - Ollama model to use (default: `llama3.2`)
- `--skip-existing` / `--no-skip-existing` - Whether to skip already processed records
- `--limit` - Limit number of records/files to process (useful for testing)

## Notes

- All scripts use the same logging format and error handling patterns
- Scripts are designed to be idempotent - safe to re-run
- All scripts create appropriate database indexes for better query performance
- Foreign key relationships ensure data integrity when records are deleted

