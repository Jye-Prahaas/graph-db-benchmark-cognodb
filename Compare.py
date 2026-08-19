import os
import time
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase
from falkordb import FalkorDB
from arango import ArangoClient
from tabulate import tabulate

load_dotenv()

CSV_PATH = "data/edges.csv"
df = pd.read_csv(CSV_PATH)
edges = list(zip(df["src"].astype(str), df["dst"].astype(str)))
sample_nodes = list(df["src"].astype(str).sample(min(100, len(df)), random_state=42))

def compile_metrics(name, throughput, load_time, lat_1hop, lat_2hop, lat_3hop, lat_lookup, lat_agg):
    return {
        "Database": name,
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
    }


def run_cypher_benchmarks(name, uri, user=None, password=None):
    
    print(f"  Starting Benchmark: {name}")
    
    auth = (user, password) if user and password else None
    driver = GraphDatabase.driver(uri, auth=auth)
    
    with driver.session() as session:
        # 1. Clean previous data
        print("-> Clearing database...")
        try:
            session.run("MATCH (n) DETACH DELETE n")
        except Exception:
            pass

        
        print("-> Setting up index/constraint...")
        try:
            session.run("CREATE CONSTRAINT FOR (p:Person) REQUIRE p.id IS UNIQUE")
        except Exception:
            try:
                session.run("CREATE INDEX ON :Person(id)")
            except Exception:
                pass

        
        print(f"-> Ingesting {len(edges)} relationships...")
        start_time = time.perf_counter()
        batch_size = 2000
        for i in range(0, len(edges), batch_size):
            batch = [{"src": s, "dst": d} for s, d in edges[i:i+batch_size]]
            session.run("""
                UNWIND $batch AS edge
                MERGE (a:Person {id: edge.src})
                MERGE (b:Person {id: edge.dst})
                CREATE (a)-[:CONNECTED_TO]->(b)
            """, batch=batch)
            print(f"   Progress: {min(i+batch_size, len(edges))}/{len(edges)} edges loaded", end="\r")

        load_time = time.perf_counter() - start_time
        throughput = len(edges) / load_time
        print(f"\n Ingest finished: {load_time:.2f}s ({throughput:.1f} edges/s)")

        
        print("-> Warming up cache...")
        for n in sample_nodes[:15]:
            session.run("MATCH (p:Person {id: $id})-[:CONNECTED_TO]->(m) RETURN count(m)", id=n).consume()

        
        print("-> Running 1-Hop traversals...")
        lat_1hop = []
        for n in sample_nodes:
            t0 = time.perf_counter()
            session.run("MATCH (p:Person {id: $id})-[:CONNECTED_TO]->(m) RETURN m.id", id=n).consume()
            lat_1hop.append((time.perf_counter() - t0) * 1000)

        
        print("-> Running 2-Hop traversals...")
        lat_2hop = []
        for n in sample_nodes:
            t0 = time.perf_counter()
            session.run("MATCH (p:Person {id: $id})-[:CONNECTED_TO*2]->(m) RETURN count(m)", id=n).consume()
            lat_2hop.append((time.perf_counter() - t0) * 1000)

        
        print("-> Running 3-Hop traversals...")
        lat_3hop = []
        for n in sample_nodes:
            t0 = time.perf_counter()
            session.run("MATCH (p:Person {id: $id})-[:CONNECTED_TO*3]->(m) RETURN count(m)", id=n).consume()
            lat_3hop.append((time.perf_counter() - t0) * 1000)

        
        print("-> Running Point Lookups...")
        lat_lookup = []
        for n in sample_nodes:
            t0 = time.perf_counter()
            session.run("MATCH (p:Person {id: $id}) RETURN p", id=n).consume()
            lat_lookup.append((time.perf_counter() - t0) * 1000)

        
        print("-> Running Aggregations...")
        lat_agg = []
        for _ in range(25):
            t0 = time.perf_counter()
            session.run("MATCH (p:Person)-[r:CONNECTED_TO]->() RETURN p.id, count(r) AS deg LIMIT 50").consume()
            lat_agg.append((time.perf_counter() - t0) * 1000)

    driver.close()
    return compile_metrics(name, throughput, load_time, lat_1hop, lat_2hop, lat_3hop, lat_lookup, lat_agg)


def run_falkordb_benchmarks(name="FalkorDB (Docker)"):
   
    print(f"  Starting Benchmark: {name}")
    
    falkor = FalkorDB(host='localhost', port=6379)
    g = falkor.select_graph('benchmark_graph')
    try:
        g.delete()
    except Exception:
        pass
    g = falkor.select_graph('benchmark_graph')

    # Create Index
    try:
        g.query("CREATE INDEX FOR (p:Person) ON (p.id)")
    except Exception:
        pass

    
    print(f"-> Ingesting {len(edges)} relationships...")
    start_time = time.perf_counter()
    batch_size = 2000
    for i in range(0, len(edges), batch_size):
        batch = [{"src": s, "dst": d} for s, d in edges[i:i+batch_size]]
        g.query("""
            UNWIND $batch AS edge
            MERGE (a:Person {id: edge.src})
            MERGE (b:Person {id: edge.dst})
            CREATE (a)-[:CONNECTED_TO]->(b)
        """, {'batch': batch})
        print(f"   Progress: {min(i+batch_size, len(edges))}/{len(edges)} edges loaded", end="\r")

    load_time = time.perf_counter() - start_time
    throughput = len(edges) / load_time
    print(f"\n Ingest finished: {load_time:.2f}s ({throughput:.1f} edges/s)")

    # Warmup
    print("-> Warming up cache...")
    for n in sample_nodes[:15]:
        g.query("MATCH (p:Person {id: $id})-[:CONNECTED_TO]->(m) RETURN count(m)", {'id': n})

   
    print("-> Running 1-Hop traversals...")
    lat_1hop = []
    for n in sample_nodes:
        t0 = time.perf_counter()
        g.query("MATCH (p:Person {id: $id})-[:CONNECTED_TO]->(m) RETURN m.id", {'id': n})
        lat_1hop.append((time.perf_counter() - t0) * 1000)

    
    print("-> Running 2-Hop traversals...")
    lat_2hop = []
    for n in sample_nodes:
        t0 = time.perf_counter()
        g.query("MATCH (p:Person {id: $id})-[:CONNECTED_TO*2]->(m) RETURN count(m)", {'id': n})
        lat_2hop.append((time.perf_counter() - t0) * 1000)

   
    print("-> Running 3-Hop traversals...")
    lat_3hop = []
    for n in sample_nodes:
        t0 = time.perf_counter()
        g.query("MATCH (p:Person {id: $id})-[:CONNECTED_TO*3]->(m) RETURN count(m)", {'id': n})
        lat_3hop.append((time.perf_counter() - t0) * 1000)

    
    print("-> Running Point Lookups...")
    lat_lookup = []
    for n in sample_nodes:
        t0 = time.perf_counter()
        g.query("MATCH (p:Person {id: $id}) RETURN p", {'id': n})
        lat_lookup.append((time.perf_counter() - t0) * 1000)

    
    print("-> Running Aggregations...")
    lat_agg = []
    for _ in range(25):
        t0 = time.perf_counter()
        g.query("MATCH (p:Person)-[r:CONNECTED_TO]->() RETURN p.id, count(r) AS deg LIMIT 50")
        lat_agg.append((time.perf_counter() - t0) * 1000)

    return compile_metrics(name, throughput, load_time, lat_1hop, lat_2hop, lat_3hop, lat_lookup, lat_agg)


def run_arangodb_benchmarks(name="ArangoDB (Docker)"):
   
    print(f"  Starting Benchmark: {name}")
    
    client = ArangoClient(hosts="http://localhost:8529")
    sys_db = client.db("_system", username="root", password="")
    
    if sys_db.has_database("benchmark_db"):
        sys_db.delete_database("benchmark_db")
    sys_db.create_database("benchmark_db")
    db = client.db("benchmark_db", username="root", password="")

    persons = db.create_collection("persons")
    connected_to = db.create_collection("connected_to", edge=True)

    print(f"-> Ingesting {len(edges)} relationships...")
    start_time = time.perf_counter()
    unique_nodes = list(set(df["src"]).union(set(df["dst"])))
    node_docs = [{"_key": str(u), "id": str(u)} for u in unique_nodes]
    edge_docs = [{"_from": f"persons/{s}", "_to": f"persons/{d}"} for s, d in edges]

    batch_size = 5000
    for i in range(0, len(node_docs), batch_size):
        persons.insert_many(node_docs[i:i+batch_size], overwrite=True)
    for i in range(0, len(edge_docs), batch_size):
        connected_to.insert_many(edge_docs[i:i+batch_size], overwrite=True)
        print(f"   Progress: {min(i+batch_size, len(edge_docs))}/{len(edge_docs)} edges loaded", end="\r")

    load_time = time.perf_counter() - start_time
    throughput = len(edges) / load_time
    print(f"\n Ingest finished: {load_time:.2f}s ({throughput:.1f} edges/s)")

    
    print("-> Warming up cache...")
    for n in sample_nodes[:15]:
        db.aql.execute("FOR v IN 1..1 OUTBOUND CONCAT('persons/', @id) connected_to RETURN count(v)", bind_vars={'id': n})

    
    print("-> Running 1-Hop traversals...")
    lat_1hop = []
    for n in sample_nodes:
        t0 = time.perf_counter()
        db.aql.execute("FOR v IN 1..1 OUTBOUND CONCAT('persons/', @id) connected_to RETURN v._key", bind_vars={'id': n})
        lat_1hop.append((time.perf_counter() - t0) * 1000)

    
    print("-> Running 2-Hop traversals...")
    lat_2hop = []
    for n in sample_nodes:
        t0 = time.perf_counter()
        db.aql.execute("FOR v IN 2..2 OUTBOUND CONCAT('persons/', @id) connected_to RETURN v._key", bind_vars={'id': n})
        lat_2hop.append((time.perf_counter() - t0) * 1000)

   
    print("-> Running 3-Hop traversals...")
    lat_3hop = []
    for n in sample_nodes:
        t0 = time.perf_counter()
        db.aql.execute("FOR v IN 3..3 OUTBOUND CONCAT('persons/', @id) connected_to RETURN v._key", bind_vars={'id': n})
        lat_3hop.append((time.perf_counter() - t0) * 1000)

    
    print("-> Running Point Lookups...")
    lat_lookup = []
    for n in sample_nodes:
        t0 = time.perf_counter()
        db.aql.execute("RETURN DOCUMENT(CONCAT('persons/', @id))", bind_vars={'id': n})
        lat_lookup.append((time.perf_counter() - t0) * 1000)

    
    print("-> Running Aggregations...")
    lat_agg = []
    for _ in range(25):
        t0 = time.perf_counter()
        db.aql.execute("FOR e IN connected_to COLLECT src = e._from WITH COUNT INTO deg LIMIT 50 RETURN {src, deg}")
        lat_agg.append((time.perf_counter() - t0) * 1000)

    return compile_metrics(name, throughput, load_time, lat_1hop, lat_2hop, lat_3hop, lat_lookup, lat_agg)


# MAIN BENCHMARK ORCHESTRATOR

if __name__ == "__main__":
    results = []

    # 1. Neo4j Docker
    try:
        results.append(run_cypher_benchmarks("Neo4j (Docker)", "bolt://127.0.0.1:7687", "neo4j", "password123"))
    except Exception as e:
        print(f"Error on Neo4j: {e}")

    # 2. Memgraph Docker
    try:
        results.append(run_cypher_benchmarks("Memgraph (Docker)", "bolt://127.0.0.1:7688"))
    except Exception as e:
        print(f"Error on Memgraph: {e}")

    # 3. FalkorDB Docker
    try:
        results.append(run_falkordb_benchmarks())
    except Exception as e:
        print(f"Error on FalkorDB: {e}")

    # 4. ArangoDB Docker
    try:
        results.append(run_arangodb_benchmarks())
    except Exception as e:
        print(f"Error on ArangoDB: {e}")

    # 5. CognoDB Cloud
    cogno_uri = os.getenv("COGNODB_URI")
    cogno_pass = os.getenv("COGNODB_PASSWORD")
    if cogno_uri and cogno_pass and "<" not in cogno_uri:
        try:
            results.append(run_cypher_benchmarks("CognoDB Cloud", cogno_uri, os.getenv("COGNODB_USER", "cognodb"), cogno_pass))
        except Exception as e:
            print(f"Error on CognoDB: {e}")
    else:
        print("\nNote: Skipping CognoDB Cloud (ensure COGNODB_URI and COGNODB_PASSWORD are in your .env)")

    # Save to CSV
    df_res = pd.DataFrame(results)
    df_res.to_csv("benchmark_results.csv", index=False)
    
    print("\n" + "="*80)
    print("FINAL BENCHMARK MATRIX (Copy this into your README.md)")
    print("="*80)
    print(tabulate(results, headers="keys", tablefmt="github"))