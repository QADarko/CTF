from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import DomainError, require
from .models import Gate, Project, ResourceRecord, new_id, now_iso
from .repository import InMemoryRepository
from .state_machine import GATE_SPECS, legal_transition, validate_gate_decision

RESOURCE_MEMORY_KEYS = {
    "REALITY": "reality",
    "QUESTION": "question",
    "PERCEPTION": "perception",
    "CLAIM": "claims",
    "EVIDENCE": "evidence_ledger",
    "EVIDENCE_GAP": "evidence_gaps",
    "OPPORTUNITY": "opportunities",
    "SPARK": "sparks",
    "IDEA": "ideas",
    "ASSUMPTION": "assumptions",
    "HUMAN_DECISION": "decision_history",
    "COMMITMENT": "commitments",
    "ROADMAP": "roadmaps",
    "CREATION_RECORD": "creation_records",
    "REALITY_SNAPSHOT": "reality_snapshots",
    "CREATION_CYCLE": "creation_cycles",
}

IMMUTABLE_WHEN_CONFIRMED = {
    "OPPORTUNITY",
    "SPARK",
    "IDEA",
    "VALUE_BOUNDARY",
    "HUMAN_DECISION",
    "DECISION_BRIEF",
    "COMMITMENT",
    "ROADMAP",
    "CREATION_RECORD",
    "BASELINE",
    "REALIZED_VALUE",
    "TRANSFORMATION",
    "REALITY_SNAPSHOT",
    "CREATION_CYCLE",
    "CLAIM",
    "EVIDENCE",
}
CONFIRMED_STATUSES = {"CONFIRMED", "SELECTED", "ACTIVE", "COMPLETED"}
CANDIDATE_STATUSES = {"CANDIDATE", "CANDIDATE_UNCONFIRMED", "PROPOSED", "DRAFT"}

RESOURCE_STAGES: dict[str, set[str]] = {
    "REALITY": {"REALITY"},
    "QUESTION": {"QUESTION"},
    "PERCEPTION": {"PERCEPTION"},
    "CLAIM": {"EVIDENCE"},
    "EVIDENCE": {"EVIDENCE", "ACTION", "VALUE_HYPOTHESIS", "TRANSFORMATION"},
    "EVIDENCE_GAP": {"EVIDENCE"},
    "OPPORTUNITY": {"OPPORTUNITY"},
    "SPARK": {"SPARK"},
    "IDEA": {"IDEA"},
    "ASSUMPTION": {"ASSUMPTIONS"},
    "FAILURE_MODE": {"ADVERSARIAL_TEST"},
    "PREMORTEM": {"ADVERSARIAL_TEST"},
    "COUNTERARGUMENT": {"ADVERSARIAL_TEST"},
    "VALUE_BOUNDARY": {"VALUE_BOUNDARY"},
    "VALUE_BOUNDARY_TEST": {"VALUE_BOUNDARY"},
    "CONSEQUENCE": {"DECISION"},
    "DECISION_BRIEF": {"DECISION"},
    "RECOMMENDATION": {"DECISION"},
    "VALIDATION_PLAN": {"DECISION"},
    "COMMITMENT": {"COMMITMENT"},
    "RESOURCE_COMMITMENT": {"COMMITMENT"},
    "OUTCOME": {"OUTCOME"},
    "MILESTONE": {"OUTCOME"},
    "ROADMAP": {"OUTCOME"},
    "ACTION": {"ACTION"},
    "EXECUTION_EVIDENCE": {"ACTION"},
    "EXECUTION_EVENT": {"ACTION"},
    "BLOCKER": {"ACTION"},
    "CREATION_RECORD": {"ACTION"},
    "STAKEHOLDER": {"VALUE"},
    "VALUE_HYPOTHESIS": {"VALUE_HYPOTHESIS"},
    "VALUE_METRIC": {"VALUE_HYPOTHESIS"},
    "BASELINE": {"VALUE_HYPOTHESIS"},
    "OBSERVATION": {"VALUE_HYPOTHESIS", "TRANSFORMATION"},
    "VALUE_EVIDENCE": {"VALUE_HYPOTHESIS", "TRANSFORMATION"},
    "REALIZED_VALUE": {"VALUE_HYPOTHESIS"},
    "NEGATIVE_EFFECT": {"VALUE_HYPOTHESIS", "TRANSFORMATION"},
    "ATTRIBUTION": {"TRANSFORMATION"},
    "COUNTERFACTUAL": {"TRANSFORMATION"},
    "ADOPTION": {"VALUE_HYPOTHESIS", "TRANSFORMATION"},
    "IMPACT": {"TRANSFORMATION"},
    "TRANSFORMATION": {"TRANSFORMATION"},
    "REALITY_SNAPSHOT": {"REALITY", "TRANSFORMATION"},
    "CREATION_CYCLE": {"ACTION", "VALUE", "VALUE_HYPOTHESIS", "TRANSFORMATION", "CYCLE_REVIEW"},
}
IMMUTABLE_WHEN_CONFIRMED.update(RESOURCE_STAGES)


class CTFService:
    def __init__(self, repo: InMemoryRepository) -> None:
        self.repo = repo

    def _memory_ref(self, project: Project, record: ResourceRecord) -> None:
        key = RESOURCE_MEMORY_KEYS.get(record.kind)
        if not key:
            return
        ref = {"id": record.id, "version": record.version, "status": record.status}
        if isinstance(project.memory[key], list):
            project.memory[key].append(ref)
        else:
            project.memory[key] = ref
        self.repo.snapshot_memory(project, [{"op": "ADD", "path": key, "value": ref}])

    def patch_memory(
        self,
        project: Project,
        operations: list[dict[str, Any]],
        expected_version: int | None,
        actor_type: str,
    ) -> dict[str, Any]:
        self.repo.check_version(project, expected_version)
        require(actor_type in {"HUMAN", "SYSTEM", "AI"}, "INVALID_INPUT", "Invalid actor type.")
        allowed_roots = set(project.memory)
        for operation in operations:
            op = str(operation.get("op", "")).upper()
            path = str(operation.get("path", ""))
            value = deepcopy(operation.get("value"))
            require(op in {"ADD", "UPDATE", "FLAG"}, "INVALID_INPUT", "Memory op must be ADD, UPDATE or FLAG.")
            require(path and path.split(".")[0] in allowed_roots, "INVALID_INPUT", "Memory path is not allowed.")
            root = path.split(".")[0]
            target = project.memory[root]
            if op == "ADD":
                require(isinstance(target, list), "INVALID_INPUT", "ADD requires a list memory target.")
                target.append(value)
            elif op == "UPDATE":
                require(not isinstance(target, list), "INVALID_INPUT", "UPDATE requires an object memory target.")
                require(isinstance(value, dict), "INVALID_INPUT", "UPDATE value must be an object.")
                if actor_type == "AI" and isinstance(target, dict) and target.get("confirmed"):
                    raise DomainError(
                        "HUMAN_AUTHORITY_REQUIRED",
                        "AI cannot overwrite confirmed Human-owned memory.",
                        403,
                    )
                target.update(value)
            else:
                require(isinstance(target, dict), "INVALID_INPUT", "FLAG requires an object target.")
                target.setdefault("flags", []).append(value)
        self.repo.touch(project)
        version = self.repo.snapshot_memory(project, operations)
        self.repo.audit(project.id, "memory_patched", actor_type, {"memory_version": version.version})
        return version.public()

    def create_resource(
        self,
        project: Project,
        kind: str,
        data: dict[str, Any],
        expected_version: int | None,
        provenance: str = "USER",
    ) -> ResourceRecord:
        self.repo.check_version(project, expected_version)
        kind = kind.upper()
        provenance = provenance.upper()
        require(provenance in {"USER", "CTF", "CO_CREATED", "DOCUMENT", "EXTERNAL_EVIDENCE", "SYSTEM"}, "INVALID_INPUT", "Invalid provenance.")
        if kind in RESOURCE_STAGES:
            require(
                project.stage in RESOURCE_STAGES[kind],
                "INVALID_STAGE_TRANSITION",
                f"{kind} cannot be created during {project.stage}.",
            )
        resource_id = new_id(kind[:4].lower())
        data["_candidate_id"] = resource_id
        self._validate_resource(project, kind, data, provenance)
        data.pop("_candidate_id", None)
        status = str(data.pop("status", "DRAFT")).upper()
        immutable = bool(data.pop("immutable", False))
        if kind == "HUMAN_DECISION":
            raise DomainError("HUMAN_GATE_REQUIRED", "Human Decisions are created only through Gate 11.")
        if status == "CONFIRMED" or (
            kind in IMMUTABLE_WHEN_CONFIRMED and status in CONFIRMED_STATUSES
        ):
            immutable = True
        record = self.repo.create_resource(
            project,
            kind,
            data,
            status=status,
            provenance=provenance,
            immutable=immutable,
            resource_id=resource_id,
        )
        self._memory_ref(project, record)
        self._create_declared_links(project, record, data)
        if kind == "CREATION_RECORD":
            self._activate_value_stage(project)
        elif kind == "COMMITMENT_REVIEW":
            project.active_gate = Gate(new_id("gate"), 15, GATE_SPECS[15].name)
            self.repo.touch(project)
            self.repo.audit(
                project.id,
                "commitment_review_requested",
                "HUMAN",
                {"commitment_review_id": record.id},
            )
        return record

    def supersede_resource(
        self,
        project: Project,
        kind: str,
        resource_id: str,
        data: dict[str, Any],
        expected_version: int | None,
        provenance: str = "USER",
    ) -> ResourceRecord:
        old = self.repo.get_resource(project, resource_id, kind.upper())
        require(
            old.kind in IMMUTABLE_WHEN_CONFIRMED and old.immutable,
            "SUPERSESSION_NOT_ALLOWED",
            "Only confirmed consequential records may be superseded.",
            409,
        )
        replacement = self.create_resource(
            project, old.kind, data, expected_version, provenance
        )
        return self.repo.supersede_resource(project, old.id, replacement.id)

    def confirm_resource(
        self,
        project: Project,
        kind: str,
        resource_id: str,
        expected_version: int | None,
        actor_type: str = "HUMAN",
    ) -> ResourceRecord:
        require(actor_type == "HUMAN", "HUMAN_AUTHORITY_REQUIRED", "Only a human can confirm a candidate record.", 403)
        record = self.repo.get_resource(project, resource_id, kind.upper())
        require(
            record.status in CANDIDATE_STATUSES or record.status == "PARSED",
            "INVALID_CONFIRMATION",
            f"{record.status} records cannot be confirmed through this action.",
            409,
        )
        require(not record.immutable, "IMMUTABLE_RECORD", "This record is already confirmed.", 409)
        self.repo.check_version(project, expected_version)
        record.status = "CONFIRMED"
        record.immutable = record.kind in IMMUTABLE_WHEN_CONFIRMED
        record.data["confirmation"] = "CONFIRMED"
        record.data["confirmed_at"] = now_iso()
        record.version += 1
        record.updated_at = now_iso()
        self.repo.touch(project)
        self.repo.audit(
            project.id,
            f"{record.kind.lower()}_confirmed",
            "HUMAN",
            {"resource_id": record.id, "kind": record.kind},
        )
        if hasattr(self.repo, "persist"):
            self.repo.persist()
        return record

    def _validate_resource(
        self, project: Project, kind: str, data: dict[str, Any], provenance: str
    ) -> None:
        if provenance in {"CTF", "SYSTEM"} and kind in {
            "VALUE_BOUNDARY",
            "HUMAN_DECISION",
            "COMMITMENT",
            "ROADMAP",
        }:
            status = str(data.get("status", "DRAFT")).upper()
            require(
                status not in {"CONFIRMED", "SELECTED", "ACTIVE", "COMPLETED"}
                and not data.get("immutable"),
                "HUMAN_AUTHORITY_REQUIRED",
                f"{kind} confirmation is Human-owned.",
                403,
            )
        if kind == "EVIDENCE":
            require(data.get("statement"), "INVALID_INPUT", "Evidence requires a statement.")
            source_id = data.get("source_id")
            if source_id:
                self.repo.get_resource(project, source_id, "EVIDENCE_SOURCE")
        elif kind == "OPPORTUNITY":
            require(data.get("derived_from"), "INVALID_GENEALOGY_REFERENCE", "Opportunity requires traceable derived_from references.")
        elif kind == "SPARK":
            require(provenance in {"USER", "CTF", "CO_CREATED"}, "INVALID_INPUT", "Spark origin is invalid.")
            require(data.get("text"), "INVALID_INPUT", "Spark requires text.")
        elif kind == "IDEA":
            require(data.get("name") and data.get("what"), "INVALID_INPUT", "Idea requires name and what.")
            data.setdefault("unknowns", [])
            data.setdefault("assumptions", [])
        elif kind == "VALUE_BOUNDARY":
            require(provenance == "USER", "HUMAN_AUTHORITY_REQUIRED", "Value Boundaries are Human-owned.", 403)
            if data.get("priority") == "NON_NEGOTIABLE":
                data["confirmed_by_human"] = False
        elif kind == "DECISION_BRIEF":
            idea = None
            if data.get("idea_id"):
                try:
                    idea = self.repo.get_resource(project, str(data["idea_id"]), "IDEA")
                except DomainError:
                    idea = None
            if idea is None:
                idea = self._selected(project, "IDEA")
            if idea is None:
                ideas = self.repo.list_resources(project, "IDEA")
                if ideas:
                    idea = self.repo.get_resource(project, ideas[-1].id, "IDEA")
            require(bool(idea), "STALE_IDEA_VERSION", "An Idea is required for the Decision Brief.")
            idea_version = data.get("idea_version")
            if idea_version is None:
                data["idea_id"] = idea.id
                data["idea_version"] = idea.version
            else:
                require(
                    str(data.get("idea_id", idea.id)) == idea.id
                    and int(idea_version) == idea.version,
                    "STALE_IDEA_VERSION",
                    "Decision Brief must match the exact Idea version.",
                )
                data["idea_id"] = idea.id
                data["idea_version"] = idea.version
        elif kind == "COMMITMENT":
            decision_id = data.get("decision_id")
            decision = self.repo.get_resource(project, decision_id, "HUMAN_DECISION")
            require(decision.data.get("decision") in {"GO", "CONDITIONAL_GO"}, "INVALID_DECISION", "Commitment requires a GO route.")
        elif kind == "OUTCOME":
            require(data.get("success_definition"), "INVALID_INPUT", "Outcome requires an observable success definition.")
            require(data.get("derived_from"), "INVALID_GENEALOGY_REFERENCE", "Orphan Outcomes are not allowed.")
        elif kind == "ACTION":
            require(data.get("why"), "INVALID_INPUT", "Every Action requires a traceable WHY.")
            if str(data.get("status", "")).upper() == "READY":
                require(data.get("owner_id"), "ACTION_OWNER_REQUIRED", "READY Action requires an owner.")
            self._validate_dependencies(project, data.get("dependencies", []), data.get("_candidate_id"))
        elif kind == "EXECUTION_EVIDENCE":
            self.repo.get_resource(project, data.get("action_id"), "ACTION")
            require(data.get("statement"), "INVALID_INPUT", "Execution Evidence requires a statement.")
        elif kind == "CREATION_RECORD":
            refs = data.get("evidence_refs", [])
            require(bool(refs), "CREATION_RECORD_NOT_SUPPORTED", "Creation Record requires Execution Evidence.")
            for ref in refs:
                self.repo.get_resource(project, ref, "EXECUTION_EVIDENCE")
        elif kind == "VALUE_HYPOTHESIS":
            self.repo.get_resource(project, data.get("stakeholder_id"), "STAKEHOLDER")
            require(data.get("statement"), "INVALID_INPUT", "Value Hypothesis requires a testable statement.")
        elif kind == "BASELINE":
            status = str(data.get("status", "UNKNOWN")).upper()
            require(not (status == "CONFIRMED" and not data.get("evidence_refs")), "VALUE_EVIDENCE_REQUIRED", "Confirmed baseline requires Evidence.")
        elif kind == "OBSERVATION":
            self.repo.get_resource(project, data.get("metric_id"), "VALUE_METRIC")
            require(data.get("observed_at") is not None, "INVALID_INPUT", "Observation requires observed_at.")
        elif kind == "REALIZED_VALUE":
            require(data.get("stakeholder_id"), "INVALID_INPUT", "Realized Value requires a stakeholder.")
            require(data.get("evidence_refs"), "VALUE_EVIDENCE_REQUIRED", "Official Realized Value requires Evidence.")
        elif kind == "IMPACT":
            require(data.get("pathway_links"), "IMPACT_PATHWAY_INCOMPLETE", "Impact requires a supported pathway.")
            require(all(x.get("status") in {"SUPPORTED", "PARTIALLY_SUPPORTED"} for x in data["pathway_links"]), "IMPACT_PATHWAY_INCOMPLETE", "Impact pathway has unsupported links.")
        elif kind == "TRANSFORMATION":
            require(len(data.get("evidence_refs", [])) >= 2, "TRANSFORMATION_EVIDENCE_INSUFFICIENT", "Transformation requires multiple Evidence references.")
            require(data.get("sustainability"), "TRANSFORMATION_EVIDENCE_INSUFFICIENT", "Transformation requires sustainability assessment.")
        elif kind == "REALITY_SNAPSHOT":
            require(str(data.get("label", "")).startswith("R"), "INVALID_INPUT", "Reality snapshot requires an R label.")
            data["status"] = "DRAFT"

    def _create_declared_links(
        self, project: Project, record: ResourceRecord, data: dict[str, Any]
    ) -> None:
        for source_id in data.get("derived_from", []):
            source = self.repo.get_resource(project, source_id)
            self.repo.add_link(project, source.kind, source.id, record.kind, record.id, "DERIVES")
        for evidence_id in data.get("evidence_refs", []):
            evidence = self.repo.get_resource(project, evidence_id)
            self.repo.add_link(project, evidence.kind, evidence.id, record.kind, record.id, "SUPPORTS")

    def _validate_dependencies(
        self, project: Project, dependencies: list[dict[str, Any]], candidate_id: str | None
    ) -> None:
        graph: dict[str, list[str]] = {}
        for action in self.repo.list_resources(project, "ACTION"):
            graph[action.id] = [
                item["action_id"]
                for item in action.data.get("dependencies", [])
                if item.get("type") == "HARD"
            ]
        if candidate_id:
            graph[candidate_id] = [
                item["action_id"] for item in dependencies if item.get("type") == "HARD"
            ]

        def visit(node: str, path: set[str]) -> None:
            if node in path:
                raise DomainError("DEPENDENCY_CYCLE_DETECTED", "Circular HARD dependency detected.")
            for child in graph.get(node, []):
                visit(child, path | {node})

        for node in graph:
            visit(node, set())

    def _selected(self, project: Project, kind: str) -> ResourceRecord | None:
        selected = [
            item for item in self.repo.list_resources(project, kind)
            if item.status in {"SELECTED", "CONFIRMED", "ACTIVE"}
        ]
        return selected[-1] if selected else None

    def decide_gate(
        self,
        project: Project,
        gate_id: str,
        decision: str,
        payload: dict[str, Any],
        expected_version: int | None,
        actor_type: str,
    ) -> dict[str, Any]:
        require(actor_type == "HUMAN", "HUMAN_AUTHORITY_REQUIRED", "Only a Human may decide a Human Gate.", 403)
        self.repo.check_version(project, expected_version)
        gate = project.active_gate
        require(gate.id == gate_id, "INVALID_GATE", "Gate is not active.")
        require(gate.status == "PENDING", "GATE_ALREADY_DECIDED", "Gate has already been decided.", 409)
        next_stage, next_gate, advances = validate_gate_decision(gate.number, project.stage, decision)
        self._validate_gate_prerequisites(project, gate.number, decision.upper(), payload)
        gate.status = "DECIDED"
        gate.decision = decision.upper()
        gate.decided_at = now_iso()
        gate.actor_type = actor_type

        decision_record: ResourceRecord | None = None
        if gate.number == 11:
            decision_record = self.repo.create_resource(
                project,
                "HUMAN_DECISION",
                {
                    "decision": decision.upper(),
                    "rationale": payload.get("rationale"),
                    "conditions": payload.get("conditions", []),
                    "idea_id": payload.get("idea_id"),
                    "idea_version": payload.get("idea_version"),
                },
                status="CONFIRMED",
                provenance="USER",
                immutable=True,
            )
            self._memory_ref(project, decision_record)
        if gate.number == 18:
            snapshot = self.repo.get_resource(project, payload.get("snapshot_id"), "REALITY_SNAPSHOT")
            snapshot.status = "CONFIRMED"
            snapshot.immutable = True
            snapshot.data["status"] = "CONFIRMED"
        if gate.number == 19 and decision.upper() == "CLOSE":
            cycle = self.repo.get_resource(project, payload.get("cycle_id"), "CREATION_CYCLE")
            cycle.status = "COMPLETED"
            cycle.immutable = True

        if advances:
            project.stage = next_stage
            if next_gate:
                spec = GATE_SPECS[next_gate]
                project.active_gate = Gate(new_id("gate"), next_gate, spec.name)
        elif gate.number == 19 and decision.upper() == "NEXT_CYCLE":
            project.stage = "REALITY"
            project.active_gate = Gate(new_id("gate"), 1, GATE_SPECS[1].name)
        elif gate.number == 14 and decision.upper() == "CONFIRM_REDECISION":
            project.active_gate = Gate(new_id("gate"), 11, GATE_SPECS[11].name)
        elif decision.upper() in {"REVISE", "ADD_MISSING", "REJECT"}:
            project.active_gate = Gate(new_id("gate"), gate.number, gate.name)

        self.repo.touch(project)
        self.repo.snapshot_memory(
            project,
            [{"op": "ADD", "path": "human_decisions", "value": {"gate": gate.number, "decision": decision.upper()}}],
        )
        self.repo.audit(
            project.id,
            f"gate_{gate.number}_decided",
            "HUMAN",
            {"gate_id": gate.id, "decision": decision.upper()},
        )
        return {
            "gate": {
                "id": gate.id,
                "number": gate.number,
                "name": gate.name,
                "status": gate.status,
                "decision": gate.decision,
            },
            "project_stage": project.stage,
            "project_version": project.version,
            "next_gate": {
                "id": project.active_gate.id,
                "number": project.active_gate.number,
                "name": project.active_gate.name,
                "status": project.active_gate.status,
            },
            "decision_record": decision_record.public() if decision_record else None,
        }

    def _validate_gate_prerequisites(
        self, project: Project, gate: int, decision: str, payload: dict[str, Any]
    ) -> None:
        requirements = {
            1: "REALITY",
            2: "QUESTION",
            3: "PERCEPTION",
            5: "OPPORTUNITY",
            6: "SPARK",
            7: "IDEA",
            8: "ASSUMPTION",
            9: "FAILURE_MODE",
            10: "VALUE_BOUNDARY",
            12: "COMMITMENT",
            13: "ROADMAP",
            16: "STAKEHOLDER",
            17: "REALIZED_VALUE",
            18: "REALITY_SNAPSHOT",
            19: "CREATION_CYCLE",
        }
        if gate == 4 and decision != "ACKNOWLEDGE_UNCERTAINTY":
            require(bool(self.repo.list_resources(project, "EVIDENCE")), "VALUE_EVIDENCE_REQUIRED", "Evidence is required.")
        kind = requirements.get(gate)
        if kind:
            require(bool(self.repo.list_resources(project, kind)), f"{kind}_REQUIRED", f"{kind} record is required.")
        if gate in {5, 6, 7}:
            selected_ids = payload.get("selected_ids", [])
            require(bool(selected_ids), "INVALID_GATE_DECISION", "Selection is required.")
            if gate == 5:
                require(len(selected_ids) <= 3, "INVALID_GATE_DECISION", "At most three Opportunities may be selected.")
            for selected_id in selected_ids:
                record = self.repo.get_resource(project, selected_id, requirements[gate])
                record.status = "SELECTED"
                if record.kind in IMMUTABLE_WHEN_CONFIRMED:
                    record.immutable = True
        if gate == 10:
            for listed in self.repo.list_resources(project, "VALUE_BOUNDARY"):
                boundary = self.repo.get_resource(project, listed.id, "VALUE_BOUNDARY")
                boundary.data["confirmed_by_human"] = True
                boundary.status = "ACTIVE"
                boundary.immutable = True
        if gate == 11:
            brief = self._selected(project, "DECISION_BRIEF") or (
                self.repo.list_resources(project, "DECISION_BRIEF")[-1]
                if self.repo.list_resources(project, "DECISION_BRIEF") else None
            )
            recommendation = self.repo.list_resources(project, "RECOMMENDATION")
            require(bool(brief), "STALE_DECISION_CONTEXT", "Current Decision Brief is required.")
            require(bool(recommendation), "STALE_DECISION_CONTEXT", "CTF Recommendation is required.")
            if decision == "CONDITIONAL_GO":
                require(payload.get("conditions") or payload.get("rationale"), "DECISION_CONDITION_REQUIRED", "Conditional GO requires a condition or explanation.")
            if decision == "GO":
                conflicts = [
                    value for value in self.repo.list_resources(project, "VALUE_BOUNDARY")
                    if value.data.get("priority") == "NON_NEGOTIABLE"
                    and value.data.get("test_result") == "CONFLICT"
                ]
                require(not conflicts, "VALUE_CONFLICT_BLOCKS_GO", "Unresolved Non-Negotiable conflict blocks GO.")
        if gate == 18:
            require(payload.get("snapshot_id"), "REALITY_SNAPSHOT_NOT_CONFIRMED", "snapshot_id is required.")
        if gate == 19 and decision == "CLOSE":
            require(payload.get("cycle_id"), "CREATION_CYCLE_NOT_READY_TO_CLOSE", "cycle_id is required.")

    def action_status(
        self,
        project: Project,
        action_id: str,
        target: str,
        expected_version: int | None,
    ) -> ResourceRecord:
        self.repo.check_version(project, expected_version)
        action = self.repo.get_resource(project, action_id, "ACTION")
        current = action.status
        target = target.upper()
        legal = {
            "PLANNED": {"READY", "CANCELLED"},
            "READY": {"IN_PROGRESS", "BLOCKED", "CANCELLED"},
            "IN_PROGRESS": {"BLOCKED", "WAITING_EXTERNAL", "DONE_UNVERIFIED", "VERIFIED"},
            "BLOCKED": {"READY", "CANCELLED"},
            "WAITING_EXTERNAL": {"READY", "IN_PROGRESS", "CANCELLED"},
            "DONE_UNVERIFIED": {"VERIFIED", "IN_PROGRESS"},
        }
        require(target in legal.get(current, set()), "INVALID_ACTION_STATUS_TRANSITION", f"{current} to {target} is not allowed.")
        if target == "READY":
            require(action.data.get("owner_id"), "ACTION_OWNER_REQUIRED", "READY Action requires an owner.")
            for dependency in action.data.get("dependencies", []):
                if dependency.get("type") == "HARD":
                    depended = self.repo.get_resource(project, dependency["action_id"], "ACTION")
                    require(depended.status == "VERIFIED", "DEPENDENCY_NOT_SATISFIED", "HARD dependency is not VERIFIED.")
        evidence = [
            item for item in self.repo.list_resources(project, "EXECUTION_EVIDENCE")
            if item.data.get("action_id") == action.id
        ]
        if (
            target == "VERIFIED"
            and current == "IN_PROGRESS"
            and action.data.get("evidence_required", False)
        ):
            target = "DONE_UNVERIFIED"
        elif target == "VERIFIED" and action.data.get("evidence_required", False):
            require(bool(evidence), "EXECUTION_EVIDENCE_REQUIRED", "Verification requires Execution Evidence.")
        action.status = target
        action.version += 1
        action.updated_at = now_iso()
        self.repo.touch(project)
        self.repo.audit(project.id, "action_status_changed", "HUMAN", {"action_id": action.id, "from": current, "to": target})
        return deepcopy(action)

    def classify_materiality(self, data: dict[str, Any]) -> str:
        mandatory = {
            "KILL_ASSUMPTION_INVALIDATED",
            "NON_NEGOTIABLE_CONFLICT",
            "DECISION_CONDITION_INVALIDATED",
            "CRITICAL_RESOURCE_REMOVED",
            "BLOCKING_LEGAL_CHANGE",
            "BLOCKING_REGULATORY_CHANGE",
        }
        return "DECISION_RELEVANT" if str(data.get("type", "")).upper() in mandatory else str(data.get("materiality", "LOCAL")).upper()

    def next_best_action(self, project: Project) -> dict[str, Any]:
        if project.active_gate.status == "PENDING" and project.active_gate.number in {12, 13, 14, 15}:
            return {"recommendation": "HUMAN_GATE", "gate": project.active_gate.number}
        open_trigger = [
            item for item in self.repo.list_resources(project, "EXECUTION_EVENT")
            if item.data.get("materiality") == "DECISION_RELEVANT" and item.status == "OPEN"
        ]
        if open_trigger:
            return {"recommendation": "REDECIDE", "reason": "Decision-relevant Reality change is open."}
        eligible = []
        for action in self.repo.list_resources(project, "ACTION"):
            if action.status not in {"PLANNED", "READY"} or not action.data.get("owner_id"):
                continue
            hard_refs = [
                dep["action_id"] for dep in action.data.get("dependencies", [])
                if dep.get("type") == "HARD"
            ]
            if all(self.repo.get_resource(project, ref, "ACTION").status == "VERIFIED" for ref in hard_refs):
                eligible.append(action)
        if not eligible:
            return {"recommendation": "WAIT", "reason": "No eligible Action is currently available."}
        eligible.sort(
            key=lambda x: (
                x.data.get("validates_kill_assumption") is True,
                x.data.get("priority") == "CRITICAL",
            ),
            reverse=True,
        )
        return {
            "recommendation": "ACTION",
            "recommended_action": eligible[0].id,
            "reason": eligible[0].data.get("why"),
            "alternatives": [item.id for item in eligible[1:3]],
        }

    def _activate_value_stage(self, project: Project) -> None:
        project.stage = "VALUE"
        project.active_gate = Gate(new_id("gate"), 16, GATE_SPECS[16].name)
        self.repo.touch(project)

    def explicit_transition(
        self, project: Project, target: str, expected_version: int | None
    ) -> dict[str, Any]:
        self.repo.check_version(project, expected_version)
        target = target.upper()
        require(
            legal_transition(project.stage, target, explicit_revision=True),
            "INVALID_STAGE_TRANSITION",
            f"Project cannot transition from {project.stage} to {target}.",
        )
        old = project.stage
        project.stage = target
        gate_number = next(
            (number for number, spec in GATE_SPECS.items() if spec.stage == target and number <= 13),
            project.active_gate.number,
        )
        project.active_gate = Gate(new_id("gate"), gate_number, GATE_SPECS[gate_number].name)
        self.repo.touch(project)
        self.repo.audit(project.id, "explicit_revision_transition", "HUMAN", {"from": old, "to": target})
        return project.public()
