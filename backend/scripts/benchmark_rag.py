import asyncio
import os
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ai.retrieval.lexical import LexicalRetriever

# We define the 10 benchmark questions and their expected targets
BENCHMARK_DATASET = [
    {"question": "How are user passwords hashed?", "expected_file": "utils.py"},
    {"question": "Where is the database connection string loaded?", "expected_file": "config.py"},
    {"question": "How is the Stripe API initialized?", "expected_file": "payment.py"},
    {"question": "Which file defines the User and Product database tables?", "expected_file": "models.py"},
    {"question": "What library is used to send verification emails?", "expected_file": "email.py"},
    {"question": "Where is the Redis caching layer implemented?", "expected_file": "cache.py"},
    {"question": "How are JWT access tokens generated?", "expected_file": "auth.py"},
    {"question": "What FastAPI routes are available for users?", "expected_file": "api.py"},
    {"question": "How do we upload avatar images to AWS S3?", "expected_file": "storage.py"},
    {"question": "Where is the hello function defined?", "expected_file": "main.py"},
]

async def run_benchmark():
    print("==================================================")
    print("          RAG Quality Benchmark Runner            ")
    print("==================================================\n")
    
    test_repo_id = uuid4()
    print(f"Target Repository ID: {test_repo_id}")
    print(f"Total Questions: {len(BENCHMARK_DATASET)}\n")
    
    file_hits = 0
    symbol_hits = 0
    
    # We will use Meet's LexicalRetriever which searches the DB using PostgreSQL FTS.
    retriever = LexicalRetriever()
    
    for i, item in enumerate(BENCHMARK_DATASET, 1):
        q = item["question"]
        expected = item["expected_file"]
        
        print(f"Q{i}: {q}")
        print(f"  Expected: {expected}")
        
        # TODO (Divu): DAY 7 AI INTEGRATION
        # Once the IncrementalIndexer and EmbeddingQueue are fully wired up,
        # uncomment the following lines to execute real RAG queries:
        #
        # results = await retriever.retrieve(query=q, repository_id=test_repo_id, top_k=5)
        # retrieved_files = [chunk.file_path.split('/')[-1] for chunk in results]
        
        # Simulating empty returns since the database is currently empty:
        retrieved_files = [] 
        
        if expected in retrieved_files:
            print("  [HIT] File found in top results!")
            file_hits += 1
        else:
            print(f"  [MISS] Retriever returned: {retrieved_files}")
        print()
        
    print("==================================================")
    print("                 FINAL RESULTS                    ")
    print("==================================================")
    print(f"File Hit Rate:   {file_hits}/{len(BENCHMARK_DATASET)} ({(file_hits/len(BENCHMARK_DATASET))*100}%)")
    print(f"Symbol Hit Rate: {symbol_hits}/{len(BENCHMARK_DATASET)} ({(symbol_hits/len(BENCHMARK_DATASET))*100}%)")
    print("==================================================")
    
    if file_hits >= 8:
        print("✅ PASS: Target >= 80% file_hit rate achieved.")
    else:
        print("❌ FAIL: Did not meet the 80% target.")
        print("\n[!] WARNING: Score is 0% because the DB currently has no chunks!")
        print("[!] Divu must finish the embedding pipeline before this script can return real scores.")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
