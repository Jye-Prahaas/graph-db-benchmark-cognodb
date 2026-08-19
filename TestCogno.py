import os
import time
from pathlib import Path
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase
from tabulate import tabulate

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

uri = os.getenv("COGNODB_URI")
user = os.getenv("COGNODB_USER", "cognodb")
password = os.getenv("COGNODB_PASSWORD")

print(f"Connecting to CognoDB Cloud at: {uri} (User: {user})")

CSV_PATH = "data/edges.csv"
df = pd.read_csv(CSV_PATH)
edges = list(zip(df["src"].astype(str), df["dst"].astype(str)))
sample_nodes = list(df["src"].astype(str).sample(min(50, len(df)), random_state=42))

# Configure driver with connection health recovery
driver = GraphDatabase.driver(
    uri, 
    auth=(user, password),
    max_connection_lifetime=60,
    connection_timeout=15.0
)

# 1. Clear & Index
with driver.session() as session:
    print("-> Clearing database...")
    try:
        session.run("MATCH (n) DETACH DELETE n")
    except Exception as e:
        print(f"Note: {e}")

    try:
        session.run("CREATE INDEX FOR (p:Person) ON (p.id)")
    except Exception:
        pass

# 2. Ingest
print(f"-> Ingesting {len(edges)} relationships...")
start_time = time.perf_counter()
batch_size = 2000
with driver.session() as session:
    for i in range(0, len(edges), batch_size):
        batch = [{"src": s, "dst": d} for s, d in edges[i:i+batch_size]]
        session.run("""
            UNWIND $batch AS edge
            MERGE (a:Person {id: edge.src})
            MERGE (b:Person {id: edge.dst})
            CREATE (a)-[:CONNECTED_TO]->(b)
        """, batch=batch)
        print(f"   Progress: {min(i+batch_size, len(edges))}/{len(edges)}...", end="\r")

load_time = time.perf_counter() - start_time
throughput = len(edges) / load_time
print(f"\n Ingest finished: {load_time:.2f}s ({throughput:.1f} edges/s)")

def measure_query(query_template, node_list=None, iterations=25):
    latencies = []
    items = node_list if node_list is not None else range(iterations)
    for item in items:
        try:
            with driver.session() as session:
                t0 = time.perf_counter()
                if node_list is not None:
                    session.run(query_template, id=item).consume()
                else:
                    session.run(query_template).consume()
                latencies.append((time.perf_counter() - t0) * 1000)
        except Exception:
            latencies.append(5000.0) # Mark as timeout if exceeded
    return latencies

# 3. Cache Warmup
print("-> Warming up cache...")
measure_query("MATCH (p:Person {id: $id})-[:CONNECTED_TO]->(m) RETURN count(m)", sample_nodes[:10])

# 4. Benchmarking queries
print("-> Measuring 1-Hop...")
lat_1hop = measure_query("MATCH (p:Person {id: $id})-[:CONNECTED_TO]->(m) RETURN m.id LIMIT 100", sample_nodes)

print("-> Measuring 2-Hop...")
lat_2hop = measure_query("MATCH (p:Person {id: $id})-[:CONNECTED_TO*2]->(m) RETURN m.id LIMIT 200", sample_nodes)

print("-> Measuring 3-Hop...")
lat_3hop = measure_query("MATCH (p:Person {id: $id})-[:CONNECTED_TO*3]->(m) RETURN m.id LIMIT 300", sample_nodes)

print("-> Measuring Lookups...")
lat_lookup = measure_query("MATCH (p:Person {id: $id}) RETURN p", sample_nodes)

print("-> Measuring Aggregations...")
lat_agg = measure_query("MATCH (p:Person)-[r:CONNECTED_TO]->() RETURN p.id, count(r) AS deg LIMIT 50")

driver.close()

row = [{
    "Database": "CognoDB Cloud",
    "Ingest (edges/s)": round(throughput, 1),
    "Load Time (s)": round(load_time, 2),
    "1-Hop p50 (ms)": round(np.percentile(lat_1hop, 50), 2),
    "1-Hop p95 (ms)": round(np.percentile(lat_1hop, 95), 2),
    "2-Hop p50 (ms)": round(np.percentile(lat_2hop, 50), 2),
    "2-Hop p95 (ms)": round(np.percentile(lat_2hop, 95), 2),
    "3-Hop p50 (ms)": round(np.percentile(lat_3hop, 50), 2),
    "3-Hop p95 (ms)": round(np.percentile(lat_3hop, 95), 2),
    "Lookup p50 (ms)": round(np.percentile(lat_lookup, 50), 2),
    "Lookup p95 (ms)": round(np.percentile(lat_lookup, 95), 2),
    "Agg p50 (ms)": round(np.percentile(lat_agg, 50), 2),
    "Agg p95 (ms)": round(np.percentile(lat_agg, 95), 2)
}]

print("\n" + "="*80)
print(tabulate(row, headers="keys", tablefmt="github"))