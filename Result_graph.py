import matplotlib.pyplot as plt
import numpy as np

# 1. Traversal Latency (p50 Log Scale)
dbs = ['CognoDB\n(Cloud)', 'FalkorDB', 'ArangoDB', 'Neo4j', 'Memgraph']
hop1 = [256.41, 2.04, 47.47, 89.30, 6.21]
hop2 = [268.14, 1.51, 52.25, 78.67, 5.48]

x = np.arange(len(dbs))
width = 0.35

fig, ax = plt.subplots(figsize=(9, 5))
rects1 = ax.bar(x - width/2, hop1, width, label='1-Hop Traversal (p50)', color='#4C72B0')
rects2 = ax.bar(x + width/2, hop2, width, label='2-Hop Traversal (p50)', color='#55A868')

ax.set_ylabel('Latency (ms) - Log Scale')
ax.set_yscale('log')
ax.set_title('Multi-Hop Traversal Latency Comparison (p50)')
ax.set_xticks(x)
ax.set_xticklabels(dbs)
ax.legend()
ax.grid(axis='y', linestyle='--', alpha=0.7)

plt.tight_layout()
plt.savefig('latency_comparison.png', dpi=300)
plt.close()

# 2. Concurrency Scaling (QPS)
clients = ['1 Client', '10 Clients', '20 Clients', '40 Clients']
neo4j_qps = [11.1, 46.9, 66.5, 79.2]
memgraph_qps = [213.9, 149.8, 149.8, 155.4]
cogno_qps = [3.5, 7.4, 59.4, 140.2]

plt.figure(figsize=(9, 5))
plt.plot(clients, neo4j_qps, marker='o', linewidth=2.5, label='Neo4j (Docker)', color='#C44E52')
plt.plot(clients, memgraph_qps, marker='s', linewidth=2.5, label='Memgraph (Docker)', color='#8172B3')
plt.plot(clients, cogno_qps, marker='^', linewidth=2.5, label='CognoDB Cloud', color='#CCB974')

plt.xlabel('Concurrency Level')
plt.ylabel('Throughput (Queries Per Second)')
plt.title('Mixed Workload Concurrency Scalability (80% Read / 20% Write)')
plt.legend()
plt.grid(True, linestyle='--', alpha=0.6)

plt.tight_layout()
plt.savefig('concurrency_scaling.png', dpi=300)
plt.close()
print("Charts saved: latency_comparison.png, concurrency_scaling.png")