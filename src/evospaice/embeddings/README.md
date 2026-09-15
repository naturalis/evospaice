# Embeddings

This directory contains the code and Azure ML job configurations for generating DNA sequence embeddings.

## Contents

- **`encoder/`**: A Python module that executes the model encoding. It provides the core functionality to read sequences (e.g., from TSV or FASTA files) and run models like **Omni-DNA-20M** and **DNABERT-S** to generate embeddings.
- **`jobs/`**: Contains Azure ML CLI v2 YAML configuration files. These files are used to dispatch encoding jobs to Azure ML compute clusters.

## Azure ML Jobs

The `jobs/` directory includes configurations for running embedding tasks on specific datasets (like the Arthropoda and Lepidoptera BIN representatives).

### Running a Job

To submit an encoding job to Azure ML, use the `az ml job create` command. Make sure you are at the root of the repository or provide the correct path to the YAML file.

Example:

```bash
az ml job create \
  --file src/evospaice/embeddings/jobs/aml-job-co1-lepidoptera-omni20m_bins.yaml \
  --workspace-name <YOUR_WORKSPACE> \
  --resource-group <YOUR_RESOURCE_GROUP>
```

### Input and Output Paths

The jobs are configured to read input data and write output embeddings directly from/to Azure ML datastores:

- **Inputs**: The `fasta_path` is mounted or downloaded from the workspace blob store (e.g., `azureml://datastores/workspaceblobstore/paths/BINs/`). This typically points to a TSV or FASTA file containing the sequences to encode.
- **Outputs**: The generated embeddings are written to the workspace blob store (e.g., `azureml://datastores/workspaceblobstore/paths/embeddings/<Dataset>/<Model>/`). The `outputs.embeddings` path in the YAML specifies the exact output location.

### Environment

The Azure ML jobs are configured to build their runtime environment using the `.devcontainer/` located at the root of the `evospaice` repository. This ensures all system and Python dependencies (like `einops` and `build-essential`) are present for the models to run efficiently on GPU compute nodes.
