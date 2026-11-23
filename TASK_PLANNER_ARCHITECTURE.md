# Task Planner architecture

## Request to verified commit

1. Repository Task Studio submits a natural-language request to `POST /api/v1/tasks/prompt-to-plan`. FastAPI checks the repository owner and requires the developer role. Intent analysis and requirement decomposition are available before execution. Ambiguous requests return clarification questions without creating a task.
2. The planner combines the repository index, symbols, findings and dependency context with the configured model. The plan critic checks structured steps and indexed paths when the index matches the plan revision. Prompt-created plans are checked again at approval.
3. Approval persists the actor, plan version, base revision and plan hash. Execution checks that the current plan still matches that approval. The executor requires a full base commit SHA.
4. The workspace manager fetches the approved SHA into an isolated Git checkout and checks out the task branch. The GitHub installation token is passed to the host Git process through a GitHub-scoped HTTP header. The sandbox container mounts Git metadata read-only.
5. The execution loop runs the approved steps. Synthesis uses the configured model and applies only validated file edits. The command runner enforces its allowlist and configured sandbox. The test runner captures actual results, and the bounded repair loop can retry eligible failures.
6. Verification compares the tested diff with the reviewed diff, checks policy scope, secrets, static findings and requirement coverage, and commits the verified changes. The recorded verification result identifies the commit SHA and an audit event stores the diff hash.

## Verified commit to draft pull request

`POST /tasks/{id}/authorize-publication` checks current Git HEAD and the recorded diff, then stores the actor and SHA. The branch push uses a SHA-to-ref refspec. `POST /tasks/{id}/create-pr` pushes and reconciles or creates a GitHub Draft PR. The API stores the PR only after GitHub returns a matching head, base, draft flag and URL. Retries reuse an existing matching draft. Agent tools cannot authorize publication.

## State and deployment

The existing task, plan, approval, execution, test, repair, verification, task event and PR tables remain the application records. Test evidence stores a diff fingerprint in the existing test-run revision field. Workspace recovery metadata sits beside the working tree. No schema migration is required.

Native asynchronous execution uses the initiating API process. PostgreSQL records and Redis event distribution do not resume an interrupted native job. The API exposes the workflow's durability mode. A remote runner requires the same task-workspace directory to be mounted at the same absolute path on the API and runner hosts. See [Azure manual actions](AZURE_MANUAL_ACTIONS.md).
