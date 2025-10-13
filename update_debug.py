#!/usr/bin/env python3

import os
import re

file_path = 'app/api/v1/retailers.py'

with open(file_path, 'r') as file:
    content = file.read()

# Add debug logging to the try-except block
modified_content = re.sub(
    r'    try:\n'
    r'        # Configure query with parameters\n'
    r'        job_config = bigquery\.QueryJobConfig\(query_parameters=query_params\)\n'
    r'        \n'
    r'        # Execute query\n'
    r'        query_job = bq_client\.query\(query, job_config=job_config\)\n'
    r'        results = query_job\.result\(\)',
    
    r'    try:\n'
    r'        # Debug log the complete query and parameters\n'
    r'        import logging\n'
    r'        logger = logging.getLogger(__name__)\n'
    r'        logger.info(f"EXECUTING QUERY with sort={sort}, order_by_clause={order_by_clause}")\n'
    r'        logger.info(f"FULL QUERY: {query}")\n'
    r'        logger.info(f"QUERY PARAMS: {query_params}")\n'
    r'        \n'
    r'        # Configure query with parameters\n'
    r'        job_config = bigquery.QueryJobConfig(query_parameters=query_params)\n'
    r'        \n'
    r'        # Execute query\n'
    r'        query_job = bq_client.query(query, job_config=job_config)\n'
    r'        results = query_job.result()',
    content
)

# Update the sort_options to use a different approach
modified_content = re.sub(
    r'    # Map sort options to actual BigQuery ORDER BY clauses\n'
    r'    sort_options = \{\n'
    r'        "newest": "fp\.scraped_date DESC",\n'
    r'        "price_asc": "IF\(ARRAY_LENGTH\(pv\.variants\) > 0, pv\.variants\[OFFSET\(0\)\]\.price, NULL\) ASC",\n'
    r'        "price_desc": "IF\(ARRAY_LENGTH\(pv\.variants\) > 0, pv\.variants\[OFFSET\(0\)\]\.price, NULL\) DESC",\n'
    r'        "name_asc": "fp\.name ASC",\n'
    r'        "name_desc": "fp\.name DESC"\n'
    r'    \}',
    
    r'    # Map sort options to actual BigQuery ORDER BY clauses - simpler approach for debugging\n'
    r'    sort_options = {\n'
    r'        "newest": "fp.scraped_date DESC",\n'
    r'        "price_asc": "1 ASC",  # Temporary placeholder to debug\n'
    r'        "price_desc": "1 DESC", # Temporary placeholder to debug\n'
    r'        "name_asc": "fp.name ASC",\n'
    r'        "name_desc": "fp.name DESC"\n'
    r'    }',
    modified_content
)

with open(file_path, 'w') as file:
    file.write(modified_content)

print(f"Updated {file_path} with debug logging and simplified sort options")
