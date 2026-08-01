AI Observatory - Product Requirements Document
Version 0.1 (Alpha)

Status: Ready for Development

1. Executive Summary
Product Name

AI Observatory

Tagline

The observability layer for AI coding agents.

Vision

AI Observatory is a 100% local-first, open-source observability platform for AI coding agents.

Instead of replacing tools like Claude Code, Codex CLI, Cursor Agent, Gemini CLI, Cline, RooCode, or future AI developers, AI Observatory quietly records their observable activity and transforms it into meaningful analytics.

Developers gain insights into productivity, costs, workflows, code evolution, prompt quality, and development habits—all while keeping every byte of data on their own machine.

No cloud.

No accounts.

No telemetry.

No vendor lock-in.

The long-term vision is to become the OpenTelemetry for AI software engineering.

2. Problem Statement

Modern AI coding agents are becoming the primary way developers write software.

However developers currently have no visibility into:

How productive their AI sessions actually are.
Which prompts work best.
Which models perform better for different tasks.
How much time is wasted regenerating solutions.
How code evolves during AI-assisted development.
Which files repeatedly consume engineering effort.
Where AI is actually saving time.

Current coding agents provide code generation.

They do not provide observability.

3. Goals

The Alpha aims to validate three hypotheses.

Goal 1

Developers want historical analytics for AI-assisted development.

Goal 2

Developers enjoy replaying AI coding sessions.

Goal 3

Developers can improve productivity through actionable recommendations.

4. Non Goals

The Alpha intentionally excludes:

User accounts
Authentication
Cloud storage
SaaS hosting
Team dashboards
Enterprise features
Billing
Marketplace
Remote synchronization
Collaboration
Mobile applications
AI-powered recommendations (initially)

Everything should function offline.

5. Core Principles
Local First

Everything runs locally.

Privacy First

No data leaves the computer.

Open Source

Anyone can inspect or modify the source.

Agent Agnostic

Support every AI coding assistant through adapters.

Extensible

New analytics modules should be pluggable.

Lightweight

Minimal CPU and RAM usage.

Passive

Never interfere with coding workflows.

6. Target Users

Primary

Claude Code users
Codex CLI users
Cursor users

Secondary

AI Engineers
Open Source Contributors
Students
Researchers
Indie Hackers
7. User Story

I install AI Observatory once.

I continue coding exactly as before.

AI Observatory silently records my sessions.

After work I open a dashboard.

I instantly understand how productive my day was.

8. Product Overview

The product consists of four components.

1. Adapter Layer

Collects events from AI coding agents.

Supported initially:

Claude Code
Codex CLI

Future:

Cursor
Gemini CLI
Cline
RooCode
OpenHands
Aider
Amp
Windsurf
2. Telemetry Engine

Normalizes all events.

Every agent becomes a common event stream.

3. Analytics Engine

Processes telemetry.

Calculates:

Productivity
Costs
Statistics
Recommendations
Timelines
4. Dashboard

Beautiful web interface.

Runs locally.

9. Architecture
                  AI Coding Agents

 Claude Code
 Codex CLI
 Cursor
 Gemini CLI
 Cline
 RooCode
        │
        ▼
=============================
     Adapter Layer
=============================
        │
        ▼
=============================
   Event Normalizer
=============================
        │
        ▼
=============================
      SQLite Database
=============================
        │
        ▼
=============================
   Analytics Engine
=============================
        │
        ▼
=============================
 Local FastAPI REST Server
=============================
        │
        ▼
=============================
   Next.js Dashboard
=============================

Everything runs locally.

No remote server exists.

10. Folder Structure
ai-observatory/

dashboard/

backend/

analytics/

database/

telemetry/

shared/

adapters/

claude/

codex/

future/

api/

docs/

tests/

scripts/
11. Local Storage
~/.ai-observatory/

database.sqlite

sessions/

analytics/

logs/

settings.json

cache/

Everything is stored locally.

12. Universal Event Model

Everything becomes events.

Example

{
  "session_id":"abc123",
  "timestamp":"2026-01-15T10:15:23",
  "agent":"claude",
  "model":"sonnet",
  "event":"file_modified",
  "file":"backend/app.py",
  "metadata":{
      "lines_added":25,
      "lines_removed":12
  }
}

Supported event types

Session Started
Session Ended
Prompt Submitted
Response Received
File Opened
File Modified
File Deleted
Terminal Command
Test Executed
Test Passed
Test Failed
Git Commit
Error
Warning
Build Started
Build Finished
13. Database Schema
Sessions
id
start_time
end_time
duration
agent
model
token_count
estimated_cost
Events
id
session_id
timestamp
event_type
metadata
Files
id
session_id
filename
additions
deletions
modifications
Commands
session_id
command
timestamp
exit_code
Prompts
session_id
prompt_length
timestamp
Statistics

Precomputed metrics.

14. Dashboard
Home Page

Display

Today's Summary

Coding Time
Sessions
Files Changed
Estimated Cost
Commands
Tests
Productivity Score

Charts

Coding Time
Sessions
Cost
Tokens
Sessions Page

Every coding session.

Columns

Date
Agent
Duration
Files
Commands
Tokens
Cost
Productivity

Click opens details.

Session Timeline

Replay session.

Example

10:21

Prompt Submitted

↓

Opened auth.py

↓

Modified middleware.py

↓

Ran pytest

↓

Tests Passed

↓

Git Commit

↓

Session Finished

This is an observable action replay, not a reconstruction of model reasoning.

Session Statistics

Show

Duration

Tokens

Files

Commands

Tests

Commits

Cost

Productivity

Errors

File Analytics

Most Modified Files

Files Edited

Lines Added

Lines Removed

Repeated Modifications

Heatmap

Prompt Analytics

Metrics

Average Prompt Length

Prompt Count

Repeated Prompts

Average Response Delay

Prompt Frequency

Long Prompt Percentage

Short Prompt Percentage

Terminal Analytics

Commands Executed

Most Common Commands

Failed Commands

Successful Commands

Build Commands

Git Commands

Search

Search by

File
Prompt
Date
Session
Command
15. Productivity Engine

Generate a score between

0–100

Factors

Positive

Tests passed
Commits
Session completion
Few regenerations

Negative

Repeated prompts
Failed builds
Repeated edits
Session abandonment

Initial implementation uses deterministic rules so scores are explainable.

16. Recommendation Engine

Alpha uses rule-based insights.

Examples

"You regenerated similar code 7 times."

"Average prompt length was only 8 words."

"Most productive sessions included automated testing."

"auth.py has been modified in 18 sessions."

"You frequently interrupt the agent before completion."

Each recommendation links back to the underlying metrics.

17. Local API

Base URL

http://localhost:3141

Endpoints

GET /sessions

GET /session/{id}

GET /timeline/{id}

GET /stats

GET /files

GET /charts

GET /recommendations

GET /search

18. Adapter Interface

Every adapter must implement

class Adapter:

    def initialize(self):
        ...

    def start_session(self):
        ...

    def capture_event(self):
        ...

    def end_session(self):
        ...

Output

Universal events only.

The analytics engine should not contain agent-specific logic.

19. Technology Stack

Frontend

Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
Recharts

Backend

FastAPI
SQLAlchemy
SQLite

Desktop Runtime

Python

Package Management

uv

Testing

pytest

Charts

Recharts
20. UI Design

Theme

Dark mode first.

Inspired by

Vercel
Linear
GitHub
Raycast

Characteristics

Minimal
Fast
Keyboard friendly
Information dense
Smooth animations
21. Privacy

AI Observatory never sends:

Source code
Prompts
Terminal history
Git repositories
Tokens
API keys
Environment variables
Personal information
Analytics

No telemetry.

No analytics.

No tracking.

No background uploads.

The application should continue functioning with the network disabled.

22. Settings

Users can configure

Data retention period
Ignored directories
Ignored repositories
Dashboard theme
Adapter enable/disable
Analytics refresh interval
Export location
23. Export

Export

JSON

CSV

Markdown summary

Future

HTML reports

PDF reports

24. Plugin System (Planned)

Support plugins for

New adapters

New dashboards

Custom analytics

Custom charts

Custom recommendation rules

The plugin API should remain stable so community extensions do not require core modifications.

25. Error Handling

The application must never interrupt a coding session.

If telemetry collection fails:

Log the error.
Disable only the affected adapter.
Continue running the dashboard.
Notify the user in the UI.

No crash should terminate the user's development workflow.

26. Performance Targets

Startup

< 2 seconds

Memory

< 200 MB idle

Database size

< 500 MB after one year of typical usage (before archival)

Dashboard

< 500 ms page transitions

Analytics refresh

< 2 seconds

Telemetry capture overhead

Negligible compared to normal development activity.

27. Future Roadmap

Not part of Alpha.

Cursor support
Gemini CLI
OpenHands
Cline
RooCode
Aider
Multi-model comparison
Team dashboards
Self-hosted collaboration
GitHub PR analytics
Code review insights
Architecture heatmaps
VS Code extension
MCP server
Live overlays
Terminal UI
Self-hosted synchronization
Public adapter SDK
28. Success Metrics

The Alpha is successful if:

Installation takes less than five minutes.
The product works completely offline.
Users keep it running for at least one week.
Users regularly open the dashboard after coding sessions.
Users identify at least one actionable improvement from the analytics.
Developers can add support for a new agent by implementing only the adapter interface.
29. Guiding Philosophy

AI Observatory should never become another cloud dashboard.

It should feel like a native developer tool—similar to Git, Docker, or SQLite.

The user owns the software.

The user owns the data.

The user controls the experience.

AI Observatory simply makes AI-assisted software development observable.

30. Alpha Deliverables
Milestone 1
Local telemetry engine
SQLite storage
Universal event schema
Claude Code adapter
Codex CLI adapter
Milestone 2
FastAPI backend
Dashboard shell
Session explorer
Timeline viewer
Milestone 3
Analytics engine
Productivity score
Recommendation engine
Search
Milestone 4
UI polish
Charts
Export
Documentation
GitHub release
Appendix A: Development Principles
Local-first by default.
Never require an internet connection after installation.
Prefer deterministic analytics over opaque AI-generated scores.
Keep adapters isolated from analytics.
Make every metric explainable.
Optimize for extensibility over premature complexity.
Build a clean event schema that can support any future AI coding agent.
Treat user privacy as a core product feature, not an optional setting.