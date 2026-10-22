# 到哪了 · Are We There Yet?

[简体中文](README.md) | **English**

**Your AI keeps working. You still can't tell where the project stands—or how far it is from being usable.**

Are We There Yet? is a skill for AI coding tools. It helps your AI maintain a delivery plan, evidence-backed progress, and clear next steps, handle routine engineering choices, and explain the tradeoffs that need your judgment.

You started with a simple goal: build a website or app with AI. Then features, content, and fixes spread across several chats. Every conversation produces something, but the overall project becomes harder to follow.

Does any of this sound familiar?

- **The main project and side tasks drift apart.** You're building an app while another chat prepares course materials, but nobody defines when those materials are ready to join the main project.
- **You have to keep asking for progress.** The AI finishes a step and stops. You keep asking, “What's left?”, “How far are we from the goal?”, and “What happens next?”
- **“Done” doesn't tell you whether it works.** Code or content exists, but it's unclear whether it was checked, can be integrated, or works as part of the complete experience.
- **You're asked to approve choices you can't assess.** The AI offers several technical options and marks one “recommended,” without explaining the effects on experience, time, cost, or risk.
- **A new chat means explaining everything again.** Goals, decisions, and failed attempts remain buried in earlier conversations.

You end up supervising the AI, collecting updates, and nudging it to continue—without a trustworthy view of the whole project.

## What it helps you do

The skill organizes scattered work into deliverables with completion criteria and dependencies. Your AI maintains the same plan and progress record as it works.

**See what this delivery includes, what has been verified, what's missing, what comes next, and when your involvement is needed.**

| Your problem | What you get |
|---|---|
| You can't see the whole project or when a side task ends | Deliverables, dependencies, parallel opportunities, and completion criteria at the start; explicit conditions for bringing side tasks back into the main project |
| You keep asking, “Where are we?” | A compact status card in chat and a persistent dashboard showing verified results, gaps, blockers, and next steps |
| You don't know whether progress and time estimates are credible | Completion based on verified milestones; remaining-time ranges only when supported, with unknowns and waiting time shown separately |
| You're asked to approve unfamiliar technical choices | The AI investigates and handles routine engineering decisions; meaningful choices include benefits, costs, risks, reversibility, and a reasoned recommendation |
| Work stalls after an interruption or a new chat | Saved goals, evidence, key decisions, failed attempts, and next steps for the next session to check and resume |

The AI updates the record at meaningful milestones, blockers, or material changes, and continues with work that is ready and already authorized. You focus on goals, priorities, and consequential tradeoffs, with fewer progress requests and unnecessary technical approvals.

[See a fictional dashboard example](examples/dashboard.md) to understand the output. The bundled example is currently in Chinese.

## When to use it

- **Starting a project with several steps:** understand the parts, deliverables, order, and opportunities to work in parallel.
- **Recovering a scattered project:** features, content, and fixes have progressed, but no one can explain what is still missing from the current delivery.
- **Working across chats or side tasks:** define boundaries, dependencies, and handoff conditions so the work comes back together.
- **Resuming after an interruption:** continue from existing results and decisions without explaining the entire project again.

It is especially useful if you delegate through natural language, have no programming background, or find it difficult to review unfamiliar engineering work. Simple questions and small one-off edits usually don't need a full project plan.

**Current version: v0.1.1, an early trial release.** Start with a small side task that has a clear delivery endpoint, then refine the approach through use.

## Install

Give your AI coding tool this instruction:

```text
Install the “到哪了 · Are We There Yet?” skill from https://github.com/PollyannC/are-we-there-yet.
The skill is in the are-we-there-yet/ directory. Install the entire folder, including scripts, references, agents, and assets.
Use the installation method supported by this tool, then check that the skill entry point and bundled helper work.
```

This private repository requires existing GitHub access. You can also download `are-we-there-yet-v0.1.1.zip` from [Releases](https://github.com/PollyannC/are-we-there-yet/releases) and install the `are-we-there-yet/` folder inside it.

This release has been tried locally in Codex, where its invocation is `$are-we-there-yet`. Other tools that support `SKILL.md` can read the same entry point, but their discovery, permissions, and capabilities need separate validation. Without file access, the collaboration rules can still be used in chat, while persistent storage and automatic calculations are limited.

## Get started

In your project chat:

```text
Use $are-we-there-yet to take over this project. Read the existing requirements and results, define the current delivery endpoint, deliverables, and dependencies, create a persistent dashboard, and continue with authorized work. Handle routine engineering choices yourself. When I need to decide, explain the benefits, costs, risks, and your recommendation.
```

To bring a side task back into focus:

```text
Use $are-we-there-yet to review this side task. Tell me what has been verified, what's missing before it can join the main project, and what counts as finished. Save the state and continue with work that can be done now.
```

To resume in a new chat:

```text
Use $are-we-there-yet to resume this project. First read .project-guide/project-state.json, check the actual deliverables, current execution state, and coordinator, then continue with the next ready task.
```

**Upgrading from the old name:** Project Guide is now “到哪了 · Are We There Yet?”, invoked as `$are-we-there-yet`. Existing projects continue using the state in `.project-guide/`; don't move or reinitialize it. After installing the new version, remove the old `project-guide` skill installation to avoid duplicate discovery. Keep the `.project-guide/` data directory inside your projects.

If the current chat doesn't discover the newly installed skill, open a new project chat or provide the path to the installed `SKILL.md` directly.

The AI should respond in your language. The bundled skill instructions, helper messages, and example dashboard are currently written in Chinese; this English README does not imply a fully localized helper.

## How progress is calculated

- Completion is the weighted proportion of leaf milestones in the current plan that have passed verification and still have valid evidence. Weights are planning estimates, not precise measurements of effort.
- Drafts, generated code, running a task, or time spent do not count as verified completion. Changed evidence files revoke the relevant completion credit and require dependent milestones to be checked again.
- If the total scope can't be quantified reliably, progress is shown as unknown. Supported remaining-time ranges account for dependencies and actual execution capacity; waiting time is shown separately.
- The persistent dashboard is a snapshot with a timestamp and revision. The AI updates it at key points. Opening the file doesn't start work or check running processes.
- One coordinator updates the authoritative state. Other workers submit reports. Coordinator generations, revision checks, and file locking help prevent stale updates from overwriting newer state.

## Scope of this release

The helper requires Python 3.9+ and uses only the standard library. Safe writes use POSIX `flock`, currently supporting macOS and Linux. Environments without reliable locking are limited to read-only state checks. This release has no cloud sync, background scheduler, live executor adapters, or third-party task-system integrations.

Enabling the skill does not expand existing permissions or automatically authorize spending, publishing, sending messages, additional agents, or irreversible actions. It records work and supports judgment; it cannot replace real verification or treat an AI's claim of completion as evidence.

The speaking-practice example is fictional. Real project state, chat history, email addresses, credentials, and runtime data are not included in the distribution.

## Repository structure

```text
are-we-there-yet/
  SKILL.md
  agents/openai.yaml
  references/
    state-and-metrics.md
    execution-and-decisions.md
    presentation.md
  scripts/are_we_there_yet.py
  assets/example-project/
  tests/test_are_we_there_yet.py
README.md
README.en.md
examples/dashboard.md
```

## Validation and feedback

Validation includes 28 helper tests, an isolated task trial, and a read-only review of a real project. The checks cover evidence validity, dependencies, scope changes, time estimates, concurrent writes, ownership transfer, recovery, and human action items. The real-project review establishes that the skill can reconcile available records; it does not establish effectiveness for all users or compatibility with every host.

Contributors can rerun the tests from the repository root:

```bash
python3 -B -m unittest discover -s are-we-there-yet/tests -v
```

Further improvements will focus on information hierarchy, update frequency, estimation evidence, and recovery. When giving feedback, describe the task goal, expected behavior, observed behavior, and any reproducible example. Remove personal information, credentials, and private project content.
