# Multi-Source Candidate Data Transformer

This is a pipeline designed to ingest, normalize, and merge candidate data from multiple conflicting sources into a single, trustworthy canonical profile. 

## Design Decisions & Approach
* **Zero Dependencies:** The core engine is built entirely using Python's standard library (`json`, `re`, `argparse`, `collections`). No external packages are required to run the pipeline.
* **Deterministic Merging:** Records are unified using the candidate's email address as the primary grouping key. 
* **Confidence Scoring:** Conflicting single-value fields (like names) are resolved by taking the value from the source with the highest assigned confidence score (e.g., Structured ATS JSON > Unstructured Recruiter Notes).
* **Robust Arrays:** Multi-value fields (like emails, phones, and skills) are merged using Python `sets` to automatically deduplicate values across different sources.

## How to Run

### Prerequisites
* Python 3.x installed on your machine.

### Execution
Run the following command from the root directory to execute the pipeline using the provided sample data:

```bash
python transformer.py --json ats_export.json --txt notes.txt --config config.json


Files Included
transformer.py: The core engine (Extract, Normalize, Merge, Project).

config.json: The runtime configuration that reshapes the final output schema.

ats_export.json: Sample structured input source.

notes.txt: Sample unstructured input source.

