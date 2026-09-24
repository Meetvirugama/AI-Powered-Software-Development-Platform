# Engineering Documentation — Index
> **Project:** AI-Powered Agentic Software Engineering Platform  
> **Created:** 2026-09-24 | **Maintained by:** All team members (Yug as primary maintainer)

---

## Document Map

| # | Document | Description | Status |
|---|---|---|---|
| [00](./00_dashboard.md) | **Project Dashboard** | Current status, sprint, team, metrics | Active |
| [01](./01_project_overview.md) | **Project Overview** | Problem statement, objective, scope, stack | Active |
| [02](./02_requirements.md) | **Requirements** | FR-### and NFR-### with status | Active |
| [03](./03_features_overview.md) | **Features Overview** | Complete feature list with owners and priorities | Active |
| [04](./04_user_roles_permissions.md) | **User Roles & Permissions** | Role matrix, auth implementation | Active |
| [05](./05_system_architecture.md) | **System Architecture** | Module map, data flows, component boundaries | Active |
| [06](./06_uml_diagrams.md) | **UML Diagrams** | Use case, activity, class, sequence, state, component | Active |
| [07](./07_database_documentation.md) | **Database Documentation** | ER diagram, tables, data dictionary | Active |
| [08](./08_api_documentation.md) | **API Documentation** | All endpoints with schemas, status codes | Active |
| [09](./09_feature_documentation.md) | **Feature Documentation** | Per-feature deep-dive with flows and files | Active |
| [10](./10_development_tasks.md) | **Development Tasks** | Master task board, dependencies, assignments | Active |
| [11](./11_testing_qa.md) | **Testing & QA** | Test plan, test cases, bug tracker | Active |
| [12](./12_deployment_devops.md) | **Deployment & DevOps** | Local setup, env config, Docker | Active |
| [13](./13_architecture_decisions.md) | **Architecture Decisions** | ADR-001 through ADR-007 | Active |
| [14](./14_changelog.md) | **Changelog** | All significant changes by date | Active |

---

## Source-of-Truth Priority

When documentation conflicts with code, use this priority:

```
Actual Source Code
      ↓
Database Schema
      ↓
API Implementation
      ↓
Configuration
      ↓
Tests
      ↓
Existing Documentation
```

---

## How to Use This Documentation

### For daily development
1. Check [Dashboard](./00_dashboard.md) for current status
2. Check [Task Board](./10_development_tasks.md) for your tasks
3. Check [API Docs](./08_api_documentation.md) before implementing a new endpoint

### When implementing a new feature
1. Check [Features Overview](./03_features_overview.md) for the feature ID and owner
2. Read [Feature Documentation](./09_feature_documentation.md) for the feature's design
3. Check [Requirements](./02_requirements.md) for related FR IDs
4. Check [Database Docs](./07_database_documentation.md) for tables needed

### When making a schema change
1. Update [Database Documentation](./07_database_documentation.md)
2. Update [API Documentation](./08_api_documentation.md) for affected endpoints
3. Update [UML Diagrams](./06_uml_diagrams.md) if class diagram affected
4. Add entry to [Changelog](./14_changelog.md)

### When making an architectural decision
1. Add ADR to [Architecture Decisions](./13_architecture_decisions.md)
2. Update [System Architecture](./05_system_architecture.md) if structure changes
3. Update [Changelog](./14_changelog.md)

---

## Change Impact Matrix

When `X` changes → update these documents:

| Changed | Update |
|---|---|
| New API endpoint | 08, 10, 11 |
| DB schema change | 06 (ER), 07, 08, 09, 14 |
| New feature | 03, 09, 10 |
| Architecture change | 05, 06, 13, 14 |
| New requirement | 02, 03 |
| New team member | 00, 10 |
| Sprint/week change | 00, 10 |
| Bug found | 11 |
| Security issue | 12, 13 |
| Deployment change | 12 |

---

## Living Documentation Rules

1. Documentation MUST reflect the **actual implementation** — not plans
2. Use `TBD` for uncertain items instead of guessing
3. Mark stubs as `⚪ Stub` or `🔵 In Progress` — not `🟢 Done`
4. Update the [Dashboard](./00_dashboard.md) when task statuses change
5. Add to [Changelog](./14_changelog.md) for every significant implementation change
6. Every PR that changes an API should update [API Documentation](./08_api_documentation.md)
7. Every PR that creates a new migration should update [Database Documentation](./07_database_documentation.md)
