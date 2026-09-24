# Workshop pre-work message

Replace the bracketed fields before sending.

---

**Subject:** Store operations with Google ADK — workshop on [date]

Hello,

In our three-hour session we will explore a store operations agent, inspect its tools and workflows, evaluate
its answers and walk through deployment and governance on Google Cloud.

The workshop labs are eight Jupyter notebooks in the
[repository](https://github.com/mr394729/cymbal-beauty-adk-workshop).
[Notebook 00](../notebooks/00_workspace_and_platform.ipynb) is the starting point;
[the notebook index](../notebooks/README.md) contains the full sequence and setup commands.

You can follow the facilitator or run the notebooks in your own checkout. To run locally, install Git and uv,
clone the repository's `main` branch, then follow the notebook setup instructions. Use JupyterLab, VS Code
with the Jupyter extension, or Vertex AI Workbench. The default cells use local data and do not require cloud credentials.

For the optional live steps, use project `[project id]` and your own workshop namespace. Follow the
[cloud setup reference](../SETUP.md) for authentication and data setup. Contact `[contact]` if you need
project access. The facilitator will share the tablet app URL and its sign-in details during the session.

If you already have a checkout, preserve any local changes and update it before the workshop:

```bash
git status --short
git fetch origin main
git switch main
git merge --ff-only origin/main
```

If Git cannot switch or fast-forward because of local work, contact `[contact]` before changing or discarding files.
We will share the reviewed commit for the session as `[commit]`.
