from code_visualizer.application.headless import HeadlessService
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.domain.drakon import (
    Action,
    If,
    Select,
    Silhouette,
    Synchronizer,
    drakon_atom_ids,
)
from code_visualizer.validation import Severity, validate_project


def test_insert_edit_and_transplant_multi_atom_block_into_if_route(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        client.insert_drakon_atom(
            diagram.id,
            "action",
            0,
            source='print("one")',
            operation_id="one",
        )
        client.insert_drakon_atom(
            diagram.id,
            "action",
            1,
            source='print("two")',
            operation_id="two",
        )
        client.insert_drakon_atom(diagram.id, "if", 2, operation_id="if")
        current = service.authority.snapshot().documents[0]
        one, two, decision = current.body.atoms
        assert isinstance(decision, If)

        moved = client.move_drakon_block(
            current.id,
            current.body.id,
            (one.id, two.id),
            decision.false_branch.id,
            0,
            operation_id="transplant",
        )

        assert isinstance(moved, CommandAccepted)
        updated = service.authority.snapshot().documents[0]
        remaining = updated.body.atoms[0]
        assert isinstance(remaining, If)
        assert [atom.id for atom in remaining.false_branch.atoms[:2]] == [one.id, two.id]

        nested = client.insert_drakon_atom(
            updated.id,
            "output",
            1,
            source='"inside true"',
            sequence_id=remaining.true_branch.id,
            operation_id="nested-output",
        )
        assert isinstance(nested, CommandAccepted)
        nested_atom = service.authority.snapshot().documents[0].body.atoms[0].true_branch.atoms[1]
        changed = client.set_drakon_text(
            updated.id,
            nested_atom.id,
            "expression",
            '"edited inside true"',
            operation_id="nested-edit",
        )
        assert isinstance(changed, CommandAccepted)
    finally:
        client.close()


def test_block_transplant_is_one_revision_and_undo_restores_exact_order(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        for index, label in enumerate(("one", "two", "three")):
            client.insert_drakon_atom(
                diagram.id,
                "action",
                index,
                source=f'print("{label}")',
                operation_id=f"insert-{label}",
            )
        before = service.authority.snapshot().documents[0]
        first, second, third = before.body.atoms
        revision = service.authority.revision

        result = client.move_drakon_block(
            before.id,
            before.body.id,
            (first.id, second.id),
            before.body.id,
            3,
            operation_id="move-two",
        )
        assert isinstance(result, CommandAccepted)
        assert result.revision == revision + 1
        assert [atom.id for atom in service.authority.snapshot().documents[0].body.atoms] == [
            third.id,
            first.id,
            second.id,
        ]

        undone = client.undo(operation_id="undo-move-two")
        assert isinstance(undone, CommandAccepted)
        assert [atom.id for atom in service.authority.snapshot().documents[0].body.atoms] == [
            first.id,
            second.id,
            third.id,
        ]
        redone = client.redo(operation_id="redo-move-two")
        assert isinstance(redone, CommandAccepted)
        assert [atom.id for atom in service.authority.snapshot().documents[0].body.atoms] == [
            third.id,
            first.id,
            second.id,
        ]
    finally:
        client.close()


def test_composite_cannot_be_moved_into_its_owned_branch(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        client.insert_drakon_atom(diagram.id, "if", 0, operation_id="if")
        current = service.authority.snapshot().documents[0]
        decision = current.body.atoms[0]
        assert isinstance(decision, If)

        result = client.move_drakon_block(
            current.id,
            current.body.id,
            (decision.id,),
            decision.true_branch.id,
            0,
            operation_id="invalid-self-move",
        )

        assert isinstance(result, CommandRejected)
        assert result.code == "DRAKON_MOVE_INTO_SELF"
        assert isinstance(service.authority.snapshot().documents[0].body.atoms[0], If)
    finally:
        client.close()


def test_move_requires_contiguous_sequence_order(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        for index in range(3):
            client.insert_drakon_atom(
                diagram.id,
                "action",
                index,
                source=f"value = {index}",
                operation_id=f"insert-{index}",
            )
        current = service.authority.snapshot().documents[0]
        first, _, third = current.body.atoms
        assert isinstance(first, Action)

        result = client.move_drakon_block(
            current.id,
            current.body.id,
            (first.id, third.id),
            current.body.id,
            3,
            operation_id="non-contiguous",
        )
        assert isinstance(result, CommandRejected)
        assert result.code == "DRAKON_MOVE_NOT_CONTIGUOUS"
    finally:
        client.close()


def test_duplicate_composite_refreshes_every_owned_id_and_is_one_undo_step(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        client.insert_drakon_atom(diagram.id, "if", 0, operation_id="insert-if")
        before = service.authority.snapshot().documents[0]
        original = before.body.atoms[0]
        assert isinstance(original, If)
        revision = service.authority.revision

        duplicated = client.duplicate_drakon_block(
            before.id,
            before.body.id,
            (original.id,),
            1,
            operation_id="duplicate-if",
        )

        assert isinstance(duplicated, CommandAccepted)
        assert duplicated.revision == revision + 1
        current = service.authority.snapshot().documents[0]
        clone = current.body.atoms[1]
        assert isinstance(clone, If)
        assert set(drakon_atom_ids(original)).isdisjoint(drakon_atom_ids(clone))
        assert clone.condition == original.condition

        assert isinstance(client.undo(operation_id="undo-duplicate"), CommandAccepted)
        assert len(service.authority.snapshot().documents[0].body.atoms) == 1
        assert isinstance(client.redo(operation_id="redo-duplicate"), CommandAccepted)
        assert len(service.authority.snapshot().documents[0].body.atoms) == 2
    finally:
        client.close()


def test_wrap_and_explicit_unwrap_preserve_or_guard_owned_content(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        for index, label in enumerate(("one", "two")):
            client.insert_drakon_atom(
                diagram.id,
                "action",
                index,
                source=f'print("{label}")',
                operation_id=f"insert-{label}",
            )
        before = service.authority.snapshot().documents[0]
        first, second = before.body.atoms
        revision = service.authority.revision

        wrapped = client.wrap_drakon_block(
            before.id,
            before.body.id,
            (first.id, second.id),
            "if",
            operation_id="wrap-if",
        )
        assert isinstance(wrapped, CommandAccepted)
        assert wrapped.revision == revision + 1
        decision = service.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(decision, If)
        assert [atom.id for atom in decision.true_branch.atoms] == [first.id, second.id]

        guarded = client.unwrap_drakon_atom(
            before.id,
            decision.id,
            operation_id="unwrap-guarded",
        )
        assert isinstance(guarded, CommandRejected)
        assert guarded.code == "DRAKON_UNWRAP_CONTENT_LOSS"

        unwrapped = client.unwrap_drakon_atom(
            before.id,
            decision.id,
            discard_other_bodies=True,
            operation_id="unwrap-explicit",
        )
        assert isinstance(unwrapped, CommandAccepted)
        assert [atom.id for atom in service.authority.snapshot().documents[0].body.atoms] == [
            first.id,
            second.id,
        ]
        assert isinstance(client.undo(operation_id="undo-unwrap"), CommandAccepted)
        assert isinstance(service.authority.snapshot().documents[0].body.atoms[0], If)
    finally:
        client.close()


def test_select_and_timed_wrappers_receive_selected_block_in_preferred_body(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        client.insert_drakon_atom(diagram.id, "action", 0, source="value = 1")
        selected = service.authority.snapshot().documents[0].body.atoms[0]

        wrapped_select = client.wrap_drakon_block(
            diagram.id,
            diagram.body.id,
            (selected.id,),
            "select",
        )

        assert isinstance(wrapped_select, CommandAccepted)
        select = service.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(select, Select)
        preferred = next(case for case in select.cases if case.id == select.preferred_case_id)
        assert preferred.body.atoms == (selected,)

        wrapped_timed = client.wrap_drakon_block(
            diagram.id,
            diagram.body.id,
            (select.id,),
            "synchronizer",
        )
        assert isinstance(wrapped_timed, CommandAccepted)
        timed = service.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(timed, Synchronizer)
        assert timed.on_time.atoms == (select,)
    finally:
        client.close()


def test_preference_case_and_silhouette_edits_use_typed_replacement(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        client.insert_drakon_atom(diagram.id, "if", 0, operation_id="insert-if")
        client.insert_drakon_atom(diagram.id, "select", 1, operation_id="insert-select")
        client.insert_drakon_atom(diagram.id, "silhouette", 2, operation_id="insert-silhouette")
        current = service.authority.snapshot().documents[0]
        decision, selection, silhouette = current.body.atoms
        assert isinstance(decision, If)
        assert isinstance(selection, Select)
        assert isinstance(silhouette, Silhouette)

        preferred = client.set_if_preferred_truth(
            current.id,
            decision.id,
            False,
            operation_id="prefer-false",
        )
        assert isinstance(preferred, CommandAccepted)
        changed_if = service.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(changed_if, If)
        assert changed_if.preferred_truth is False

        added_case = client.add_select_case(
            current.id,
            selection.id,
            label="Additional",
            condition="value == 2",
            operation_id="add-case",
        )
        assert isinstance(added_case, CommandAccepted)
        changed_select = service.authority.snapshot().documents[0].body.atoms[1]
        assert isinstance(changed_select, Select)
        assert [case.label for case in changed_select.cases] == [
            "First",
            "Additional",
            "Otherwise",
        ]

        added_state = client.add_silhouette_branch(
            current.id,
            silhouette.id,
            name="Archive",
            operation_id="add-state",
        )
        assert isinstance(added_state, CommandAccepted)
        changed_silhouette = service.authority.snapshot().documents[0].body.atoms[2]
        assert isinstance(changed_silhouette, Silhouette)
        assert changed_silhouette.branches[-1].name == "Archive"
        assert (
            changed_silhouette.branches[-2].target_branch_id == changed_silhouette.branches[-1].id
        )
        assert not [
            item
            for item in validate_project(service.authority.snapshot())
            if item.severity is Severity.ERROR
        ]
    finally:
        client.close()
