# Texas road-network dataset

Source: Stanford SNAP, [Texas road network](https://snap.stanford.edu/data/roadNet-TX.html).

Download [roadNet-TX.txt.gz](https://snap.stanford.edu/data/roadNet-TX.txt.gz) and place it in this directory without extracting it. From the repository root on Windows:

```powershell
Invoke-WebRequest https://snap.stanford.edu/data/roadNet-TX.txt.gz -OutFile data/roadNet-TX.txt.gz
Get-FileHash data/roadNet-TX.txt.gz -Algorithm SHA256
```

The compressed file used for the existing local pilot has SHA-256:

```text
1bc0ce058546ae66101d57af7c16de37225e37778ad2e3781b4f7bf3a28cb41f
```

The loader preserves the raw file and interprets the network as undirected and unweighted, following the dataset description. Its normalized graph contains 1,379,917 nodes and 1,921,660 undirected edges; the input has 3,843,320 edge rows including reverse connections. Refer to the source page for dataset provenance and citation information.

The small synthetic graph in `examples/tiny-roads.txt` runs without downloading this dataset. Generated experimental outputs are not included in the repository; replay instructions are in the main README.
