---
name: jetson-app-dev
description: Build or scaffold Seeed Jetson applications. Use when users request CV, GenAI, multimodal, or robotics app development on Jetson/reComputer and need compatibility-safe implementation steps.
metadata:
  short-description: Build Jetson apps safely
---

# Jetson App Dev Skill

## Trigger
Use this skill when user requests new Jetson application development.

## Workflow
1. Collect Jetson facts as structured JSON.
2. Run compatibility analysis with `app-dev` profile.
3. If analysis is `blocked`, stop and report only safe alternatives.
4. If analysis is `needs-adjustments`, execute low/medium-risk actions first.
5. Scaffold the smallest runnable app for the target domain.
6. Add optimization tasks only after baseline success.

## Deterministic Commands
```bash
bash ../../shared/scripts/collect_jetson_facts.sh \
  --local \
  --output /tmp/jetson-facts.json

python3 ../../shared/scripts/analyze_compatibility.py \
  --facts /tmp/jetson-facts.json \
  --matrix ../../shared/references/jetpack_compatibility_matrix.json \
  --profile app-dev \
  --app-domain "<cv|genai|robotics|general>" \
  --output /tmp/jetson-analysis-app-dev.json
```

## Output Contract
- `facts_summary`
- `compatibility_status` (`ready|needs-adjustments|blocked`)
- `recommended_actions` with `risk_level/rollback_hint/verify_command`
- minimal implementation plan and verification checklist

## References
- `../../shared/references/application_topics.md`
- `../../shared/references/troubleshooting_checklists.md`
- `../../shared/references/jetpack_compatibility_matrix.json`
- `../../shared/references/dependency_mapping_rules.md`
- `../../shared/references/conflict_resolution_playbook.md`
