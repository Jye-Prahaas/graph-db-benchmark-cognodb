import os
import time
import random
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from neo4j import GraphDatabase
from tabulate import tabulate
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

CSV_PATH = "data/edges.csv"
df = pd.read_csv(CSV_PATH)
sample_nodes = list(df["src"].astype(str).sample(min(200, len(df)), random_state=42))

TARGETS = [
    ("Neo4j (Docker)", "bolt://127.0.0.1:7687", ("neo4j", "password123")),
    ("Memgraph (Docker)", "bolt://127.0.0.1:7688", None),
]

# Add CognoDB Cloud
cogno_uri = os.getenv("COGNODB_URI")
cogno_user = os.getenv("COGNODB_USER", "cognodb")
cogno_pass = os.getenv("COGNODB_PASSWORD")
if cogno_uri:
    TARGETS.append(("CognoDB Cloud", cogno_uri, (cogno_user, cogno_pass)))

def worker_task(driver, duration_sec=8):
    count = 0
    end_time = time.time() + duration_sec
    while time.time() < end_time:
        node = random.choice(sample_nodes)
        try:
            with driver.session() as s:
                if random.random() < 0.8:  # 80% Read
                    s.run("MATCH (p:Person {id: $id})-[:CONNECTED_TO]->(m) RETURN m.id LIMIT 10", id=node).consume()
                else:  # 20% Write
                    s.run("MERGE (p:Person {id: $id}) SET p.last_update = timestamp()", id=node).consume()
            count += 1
        except Exception:
            pass
    return count

concurrency_levels = [1, 10, 20, 40]
results = []

for name, uri, auth in TARGETS:
    print(f"Running concurrency tests on {name}...")
    driver = GraphDatabase.driver(uri, auth=auth)
    row = {"Database": name}
    for c in concurrency_levels:
        with ThreadPoolExecutor(max_workers=c) as executor:
            futures = [executor.submit(worker_task, driver, 8) for _ in range(c)]
            total_ops = sum(f.result() for f in futures)
            row[f"{c} Clients (QPS)"] = round(total_ops / 8.0, 1)
    driver.close()
    results.append(row)

df_out = pd.DataFrame(results)
df_out.to_csv("concurrency_results.csv", index=False)

print("\n" + "="*60)
print("MIXED WORKLOAD CONCURRENCY MATRIX (QPS)")
print("="*60)
print(tabulate(results, headers="keys", tablefmt="github"))