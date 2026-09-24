# Runtime configuration

[Application](../README.md) · [Deployment](../../../deployment/README.md)

`envs/dev.yaml`, `envs/preprod.yaml` and `envs/prod.yaml` configure the model, reasoning effort, runtime
identity, query limits and traffic policy. Project and participant namespace come from the environment.

The workshop uses the same model and MEDIUM thinking setting across environments so promotion preserves
the evaluated behavior. Identity, scaling, approvals and traffic policy can differ. A future model or thinking
change is a release change and should carry new evaluation evidence.

The configured model endpoint and runtime region serve different purposes; notebook 00 displays both.
Engine discovery uses namespace/environment labels. Never commit credentials or a personal engine ID here.
