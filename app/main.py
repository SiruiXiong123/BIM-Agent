"""Streamlit entry point for upload, door confirmation, and review results."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.review.models import (
    DoorReviewResult,
    DoorReviewStatus,
    ReviewBatchResult,
    ReviewPreparation,
    ReviewProgressEvent,
    ReviewSelection,
    ReviewStage,
)
from src.review.preparation_cache import (
    PreparationSnapshotError,
    PreparationSnapshotStore,
)
from src.review.service import ReviewService
from src.rules.result_cache import T4ResultCache
from src.schemas.assessment import EvacuationDoorClass
from src.search.iterative.building_evidence_cache import BuildingEvidenceCache


SESSION_KEYS_TO_CLEAR = (
    "preparation",
    "review_selection",
    "review_result",
    "candidate_editor",
)

CANDIDATE_WIDGET_PREFIXES = (
    "candidate_occupant_load_",
    "candidate_include_",
)


CLASSIFICATION_LABELS = {
    EvacuationDoorClass.EVACUATION_DOOR: "疏散门",
    EvacuationDoorClass.UNCERTAIN: "待确认",
    EvacuationDoorClass.NON_EVACUATION_DOOR: "非疏散门",
}

PREPARATION_SNAPSHOT_DIR = (
    PROJECT_ROOT / "artifacts" / "runtime" / "preparations"
)


def parse_sample_limit(raw_value: str) -> int | None:
    """Parse the UI's positive integer or ``all`` sample-limit contract."""

    normalized = str(raw_value or "").strip().lower()
    if normalized == "all":
        return None
    if not normalized:
        raise ValueError("请输入正整数，或输入 all 处理全部门。")
    try:
        value = int(normalized)
    except ValueError as exc:
        raise ValueError("处理数量只能是正整数或 all。") from exc
    if value <= 0 or str(value) != normalized:
        raise ValueError("处理数量必须是正整数，或输入 all。")
    return value


def reset_downstream_state(state: MutableMapping[str, Any]) -> None:
    """Clear all data that must never survive a new preparation run."""

    for key in SESSION_KEYS_TO_CLEAR:
        state[key] = None
    for key in list(state):
        if str(key).startswith(CANDIDATE_WIDGET_PREFIXES):
            del state[key]
    state["evidence_cache"] = BuildingEvidenceCache()
    state["t4_cache"] = T4ResultCache()


def reset_project_state(state: MutableMapping[str, Any]) -> None:
    """Clear one uploaded project and remove its controlled temp file."""

    _remove_controlled_upload(state.get("uploaded_ifc_path"))
    reset_downstream_state(state)
    state["upload_signature"] = None
    state["uploaded_ifc_path"] = None
    state["uploaded_ifc_name"] = None


def initialize_session_state(state: MutableMapping[str, Any]) -> None:
    """Create per-session state without sharing either review cache."""

    defaults: dict[str, Any] = {
        "upload_signature": None,
        "uploaded_ifc_path": None,
        "uploaded_ifc_name": None,
        "preparation": None,
        "review_selection": None,
        "review_result": None,
        "candidate_editor": None,
    }
    for key, value in defaults.items():
        if key not in state:
            state[key] = value
    if "evidence_cache" not in state:
        state["evidence_cache"] = BuildingEvidenceCache()
    if "t4_cache" not in state:
        state["t4_cache"] = T4ResultCache()


def create_preparation_snapshot_store() -> PreparationSnapshotStore:
    """Return the local snapshot store used to resume completed T1/T2 work."""

    return PreparationSnapshotStore(PREPARATION_SNAPSHOT_DIR)


def restore_preparation_from_query(state: MutableMapping[str, Any]) -> None:
    """Restore a completed preparation from a validated ``resume`` token."""

    if isinstance(state.get("preparation"), ReviewPreparation):
        return
    token = st.query_params.get("resume")
    if not token:
        return
    try:
        preparation = create_preparation_snapshot_store().load(str(token))
    except PreparationSnapshotError as exc:
        st.error(f"无法恢复准备结果：{exc}")
        return
    state["preparation"] = preparation
    state["upload_signature"] = f"snapshot:{preparation.source_sha256}"
    state["uploaded_ifc_path"] = None
    state["uploaded_ifc_name"] = preparation.source_filename


def register_uploaded_ifc(
    state: MutableMapping[str, Any],
    *,
    filename: str,
    content: bytes,
) -> Path:
    """Persist a new upload and clear state only when the project changes."""

    safe_name = Path(filename).name
    if Path(safe_name).suffix.lower() != ".ifc":
        raise ValueError("只支持扩展名为 .ifc 的文件。")
    if not content:
        raise ValueError("上传的 IFC 文件为空。")
    digest = hashlib.sha256(content).hexdigest()
    signature = f"{safe_name}:{digest}"
    current_path = state.get("uploaded_ifc_path")
    if state.get("upload_signature") == signature and current_path:
        path = Path(str(current_path))
        if path.is_file():
            return path

    reset_project_state(state)
    upload_dir = Path(tempfile.mkdtemp(prefix="bim_agent_upload_"))
    destination = upload_dir / safe_name
    destination.write_bytes(content)
    state["upload_signature"] = signature
    state["uploaded_ifc_path"] = str(destination)
    state["uploaded_ifc_name"] = safe_name
    return destination


def create_review_service() -> ReviewService:
    """Build provider clients lazily from the project's existing .env file."""

    env_path = PROJECT_ROOT / ".env"
    classification_client = OpenAICompatibleJSONClient.from_env(
        env_path,
        model_env_key="evacuation_door_model_name",
        timeout_env_key="evacuation_door_timeout_seconds",
        max_output_tokens_env_key="evacuation_door_max_output_tokens",
        enable_thinking_env_key="evacuation_door_enable_thinking",
        default_max_output_tokens=768,
        default_enable_thinking=False,
    )
    review_client = OpenAICompatibleJSONClient.from_env(
        env_path,
        model_env_key="model_name",
    )
    return ReviewService(
        classification_client,
        review_client=review_client,
    )


def render_header(*, active_step: int) -> None:
    st.markdown(
        """
        <div class="hero-card">
          <div class="eyebrow">BIM AGENT · EVACUATION REVIEW</div>
          <h1>疏散门净宽智能审查</h1>
          <p>上传 IFC 模型，先完成门构件解析与疏散门识别，再进入规范证据检索和规则检查。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    step_labels = ("上传与准备", "门确认", "执行与结果")
    steps = "".join(
        (
            f'<div class="step{" active" if index == active_step else ""}">'
            f"<span>{index:02d}</span><b>{label}</b></div>"
        )
        for index, label in enumerate(step_labels, start=1)
    )
    st.markdown(
        f"""
        <div class="step-row">
          {steps}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_upload_module() -> None:
    st.subheader("上传 IFC 模型")
    st.caption("当前模块只执行 IFC 解析和门类型识别，不会开始规范检索。")
    left, right = st.columns([2.2, 1], gap="large")
    with left:
        uploaded_file = st.file_uploader(
            "选择 IFC 文件",
            type=["ifc"],
            help="支持 IFC2X3/IFC4；单文件最大大小受 Streamlit 配置限制。",
            key="ifc_uploader",
        )
    with right:
        sample_limit = st.text_input(
            "处理门数量",
            value="10",
            help="输入正整数 N 处理前 N 扇门；输入 all 处理全部门。",
            key="sample_limit_input",
        )

    if uploaded_file is None:
        if st.session_state.get("upload_signature") is not None:
            reset_project_state(st.session_state)
        st.info("请先上传 IFC 文件，然后选择本次需要处理的门数量。")
        return

    try:
        uploaded_path = register_uploaded_ifc(
            st.session_state,
            filename=uploaded_file.name,
            content=uploaded_file.getvalue(),
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    size_mb = uploaded_path.stat().st_size / (1024 * 1024)
    st.markdown(
        f"<div class='file-chip'>已选择 <b>{uploaded_file.name}</b> · {size_mb:.1f} MB</div>",
        unsafe_allow_html=True,
    )

    if st.button(
        "解析并识别门",
        type="primary",
        use_container_width=True,
        key="prepare_button",
    ):
        _run_preparation(uploaded_path, sample_limit)


def _run_preparation(uploaded_path: Path, raw_limit: str) -> None:
    try:
        max_doors = parse_sample_limit(raw_limit)
    except ValueError as exc:
        st.error(str(exc))
        return

    reset_downstream_state(st.session_state)
    progress_bar = st.progress(0, text="正在初始化 IFC 解析…")
    status_box = st.empty()

    def on_progress(event: ReviewProgressEvent) -> None:
        if event.total > 0:
            fraction = min(event.current / event.total, 1.0)
        else:
            fraction = 0.05
        progress_bar.progress(fraction, text=event.message)
        door_suffix = f" · {event.door_id}" if event.door_id else ""
        status_box.caption(f"{event.stage.value.upper()}{door_suffix}")

    try:
        service = create_review_service()
        with st.spinner("正在解析 IFC 并调用模型识别疏散门…"):
            preparation = service.prepare_ifc(
                uploaded_path,
                max_doors=max_doors,
                progress=on_progress,
            )
    except Exception as exc:
        progress_bar.empty()
        status_box.empty()
        st.error(f"准备阶段失败：{type(exc).__name__}: {exc}")
        return

    st.session_state["preparation"] = preparation
    try:
        resume_token = create_preparation_snapshot_store().save(preparation)
    except (OSError, PreparationSnapshotError) as exc:
        st.warning(f"准备结果已完成，但无法生成恢复链接：{exc}")
    else:
        st.query_params["resume"] = resume_token
    progress_bar.progress(1.0, text="上传与准备完成")
    status_box.caption("AWAITING_CONFIRMATION")
    st.rerun()


def render_preparation_summary(preparation: ReviewPreparation) -> None:
    st.divider()
    st.subheader("模型准备结果")
    st.success("IFC 解析和门类型识别已完成，可以进入门确认阶段。")
    columns = st.columns(5)
    metrics = (
        ("IFC Schema", preparation.ifc_schema),
        ("模型总门数", preparation.total_ifc_door_count),
        ("本次处理", preparation.door_count),
        ("确认疏散门", preparation.confirmed_evacuation_door_count),
        ("待确认", preparation.uncertain_door_count),
    )
    for column, (label, value) in zip(columns, metrics, strict=True):
        column.metric(label, value)

    st.caption(
        f"文件：{preparation.source_filename} · 项目ID：{preparation.project_id} · "
        f"单位换算：1 IFC单位 = {preparation.unit_scale_to_mm:g} mm"
    )
    if preparation.parser_warnings or preparation.parser_errors:
        with st.expander("查看解析提示"):
            for warning in preparation.parser_warnings:
                st.warning(warning)
            for error in preparation.parser_errors:
                st.error(error)


def build_candidate_editor_rows(
    preparation: ReviewPreparation,
) -> list[dict[str, Any]]:
    """Build the editable, presentation-only view of T1/T2 candidates."""

    return [
        {
            "door_id": candidate.door_id,
            "overall_width_mm": candidate.overall_width_mm,
            "classification": CLASSIFICATION_LABELS[candidate.raw_classification],
            "confidence": candidate.raw_confidence,
            "occupant_load": candidate.occupant_load,
            "include_in_review": (
                candidate.raw_classification
                is EvacuationDoorClass.EVACUATION_DOOR
            ),
        }
        for candidate in preparation.candidates
    ]


def build_review_selection(
    preparation: ReviewPreparation,
    editor_rows: Sequence[Mapping[str, Any]],
) -> ReviewSelection:
    """Convert edited rows into the existing auditable selection contract."""

    candidates_by_id = {
        candidate.door_id: candidate for candidate in preparation.candidates
    }
    rows_by_id: dict[str, Mapping[str, Any]] = {}
    for row in editor_rows:
        door_id = str(row.get("door_id") or "").strip()
        if not door_id or door_id in rows_by_id:
            raise ValueError("门确认表包含空白或重复的门 ID，请重新载入页面。")
        rows_by_id[door_id] = row
    if set(rows_by_id) != set(candidates_by_id):
        raise ValueError("门确认表与当前 IFC 准备结果不一致，请重新执行解析。")

    included_uncertain_ids: list[str] = []
    occupant_load_overrides: dict[str, int] = {}
    for candidate in preparation.candidates:
        row = rows_by_id[candidate.door_id]
        requested = _coerce_checkbox(row.get("include_in_review"))
        if (
            candidate.raw_classification
            is EvacuationDoorClass.NON_EVACUATION_DOOR
            and requested
        ):
            raise ValueError(
                f"{candidate.door_id} 已被判定为非疏散门，不能手动加入；"
                "当前版本只允许加入待确认门。"
            )
        if candidate.raw_classification is EvacuationDoorClass.UNCERTAIN:
            if not requested:
                continue
            included_uncertain_ids.append(candidate.door_id)
        elif (
            candidate.raw_classification
            is EvacuationDoorClass.NON_EVACUATION_DOOR
        ):
            continue

        occupant_load = _coerce_positive_integer(
            row.get("occupant_load"),
            field_name=f"{candidate.door_id} 的疏散人数",
        )
        if occupant_load != candidate.occupant_load:
            occupant_load_overrides[candidate.door_id] = occupant_load

    return ReviewSelection(
        included_uncertain_door_ids=included_uncertain_ids,
        occupant_load_overrides=occupant_load_overrides,
    )


def render_door_confirmation_module(preparation: ReviewPreparation) -> None:
    """Render candidate confirmation and occupant-load correction controls."""

    st.divider()
    st.subheader("确认参与检查的门")
    st.caption(
        "已确认的疏散门会自动进入后续流程；待确认门可手动勾选；"
        "非疏散门不能加入。疏散人数未修改时沿用当前值。"
    )
    if st.button(
        "返回并更换模型",
        use_container_width=False,
        key="change_model_button",
    ):
        st.query_params.clear()
        reset_project_state(st.session_state)
        st.rerun()

    normalized_rows = _render_candidate_table(preparation)
    st.session_state["candidate_editor"] = normalized_rows

    if st.button(
        "NEXT · 进入执行阶段",
        type="primary",
        use_container_width=True,
        key="confirmation_next_button",
    ):
        try:
            selection = build_review_selection(preparation, normalized_rows)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state["review_selection"] = selection
        st.session_state["review_result"] = None
        st.rerun()


def _render_candidate_table(
    preparation: ReviewPreparation,
) -> list[dict[str, Any]]:
    """Render a dependency-light table with row-specific edit permissions."""

    widths = (1.4, 1.3, 1.1, 0.8, 1.0, 1.0)
    headings = (
        "门 ID",
        "OverallWidth (mm)",
        "疏散门分类",
        "置信度",
        "疏散人数",
        "加入后续检查",
    )
    header_columns = st.columns(widths, gap="small")
    for column, heading in zip(header_columns, headings, strict=True):
        column.markdown(f"**{heading}**")

    rows: list[dict[str, Any]] = []
    for candidate in preparation.candidates:
        columns = st.columns(widths, gap="small", vertical_alignment="center")
        columns[0].markdown(f"`{candidate.door_id}`")
        columns[1].write(f"{candidate.overall_width_mm:.0f}")
        columns[2].write(CLASSIFICATION_LABELS[candidate.raw_classification])
        columns[3].write(
            "—"
            if candidate.raw_confidence is None
            else f"{candidate.raw_confidence:.2f}"
        )
        editable = (
            candidate.raw_classification is not EvacuationDoorClass.NON_EVACUATION_DOOR
        )
        occupant_load = columns[4].number_input(
            f"{candidate.door_id} 疏散人数",
            min_value=1,
            step=1,
            value=candidate.occupant_load,
            disabled=not editable,
            label_visibility="collapsed",
            key=(
                f"candidate_occupant_load_{preparation.source_sha256}_"
                f"{candidate.index}"
            ),
        )
        can_confirm = (
            candidate.raw_classification is EvacuationDoorClass.UNCERTAIN
        )
        include_in_review = columns[5].checkbox(
            f"{candidate.door_id} 加入后续检查",
            value=(
                candidate.raw_classification
                is EvacuationDoorClass.EVACUATION_DOOR
            ),
            disabled=not can_confirm,
            label_visibility="collapsed",
            key=(
                f"candidate_include_{preparation.source_sha256}_"
                f"{candidate.index}"
            ),
        )
        rows.append(
            {
                "door_id": candidate.door_id,
                "overall_width_mm": candidate.overall_width_mm,
                "classification": CLASSIFICATION_LABELS[
                    candidate.raw_classification
                ],
                "confidence": candidate.raw_confidence,
                "occupant_load": occupant_load,
                "include_in_review": include_in_review,
            }
        )
        st.markdown("<div class='candidate-divider'></div>", unsafe_allow_html=True)
    return rows


def render_selection_ready(
    preparation: ReviewPreparation,
    selection: ReviewSelection,
) -> None:
    """Run T3-T5 on demand, then render the human-facing result page."""

    selected_count = (
        preparation.confirmed_evacuation_door_count
        + len(selection.included_uncertain_door_ids)
    )
    st.divider()
    st.subheader("门确认已完成")
    st.success(f"已确认 {selected_count} 扇门进入后续检查流程。")
    summary_columns = st.columns(3)
    summary_columns[0].metric(
        "自动加入疏散门",
        preparation.confirmed_evacuation_door_count,
    )
    summary_columns[1].metric(
        "手动加入待确认门",
        len(selection.included_uncertain_door_ids),
    )
    summary_columns[2].metric(
        "人数修正",
        len(selection.occupant_load_overrides),
    )
    result = st.session_state.get("review_result")
    if isinstance(result, ReviewBatchResult):
        render_review_result(result)
        left, right = st.columns(2)
        if left.button(
            "返回修改门选择",
            use_container_width=True,
            key="back_to_confirmation_after_result_button",
        ):
            _return_to_confirmation()
        if right.button(
            "使用当前选择重新执行",
            use_container_width=True,
            key="rerun_review_button",
        ):
            st.session_state["review_result"] = None
            st.rerun()
        return

    st.info(
        "点击开始后将依次执行 T3 证据检索、T4 规则计算和 T5 结果说明。"
        "同复用键的门共享结果，不同组最多 4 路并发。"
    )
    left, right = st.columns([1, 2])
    if left.button(
        "返回修改门选择",
        use_container_width=True,
        key="back_to_confirmation_button",
    ):
        _return_to_confirmation()
    if right.button(
        "开始执行 T3–T5",
        type="primary",
        use_container_width=True,
        disabled=selected_count == 0,
        key="start_review_button",
    ):
        _run_review(preparation, selection)


def _run_review(
    preparation: ReviewPreparation,
    selection: ReviewSelection,
) -> None:
    """Execute the framework-neutral review service with UI progress only."""

    progress_bar = st.progress(0, text="正在初始化规范检查…")
    status_box = st.empty()

    def on_progress(event: ReviewProgressEvent) -> None:
        fraction = _overall_review_progress(event)
        progress_bar.progress(fraction, text=event.message)
        door_suffix = f" · {event.door_id}" if event.door_id else ""
        status_box.caption(f"{event.stage.value.upper()}{door_suffix}")

    try:
        service = create_review_service()
        with st.spinner("正在执行证据检索与门净宽检查…"):
            result = service.run_review(
                preparation,
                selection,
                evidence_cache=st.session_state["evidence_cache"],
                t4_cache=st.session_state["t4_cache"],
                progress=on_progress,
            )
    except Exception as exc:
        progress_bar.empty()
        status_box.empty()
        st.error(f"执行阶段失败：{type(exc).__name__}: {exc}")
        return

    st.session_state["review_result"] = result
    progress_bar.progress(1.0, text="T3–T5 执行完成")
    status_box.caption("COMPLETE")
    st.rerun()


def _overall_review_progress(event: ReviewProgressEvent) -> float:
    """Map the three backend stages onto one stable Streamlit progress bar."""

    stage_offsets = {
        ReviewStage.T3: 0.0,
        ReviewStage.T4: 1 / 3,
        ReviewStage.T5: 2 / 3,
        ReviewStage.COMPLETE: 1.0,
    }
    if event.stage is ReviewStage.COMPLETE:
        return 1.0
    offset = stage_offsets.get(event.stage, 0.0)
    within_stage = event.current / event.total if event.total else 0.0
    return min(offset + within_stage / 3, 0.99)


def build_result_table_rows(
    result: ReviewBatchResult,
) -> list[dict[str, Any]]:
    """Build visible result rows without exposing the machine-result field."""

    return [
        {
            "door_id": item.door_id,
            "overall_width_mm": item.overall_width_mm,
            "actual_clear_width_mm": item.actual_clear_width_mm,
            "required_clear_width_mm": item.required_clear_width_mm,
            "result": item.display_result or "—",
            "t3_reused": item.t3_cache_hit,
            "t4_reused": item.t4_cache_hit,
            "status": _status_label(item.status),
        }
        for item in result.results
    ]


def render_review_result(result: ReviewBatchResult) -> None:
    """Render final metrics, visible result table, reasons, and audit export."""

    st.divider()
    st.subheader("检查结果")
    metric_columns = st.columns(5)
    metrics = (
        ("进入检查", result.total_doors),
        ("完成", result.reviewed_doors),
        ("合格", result.passed_doors),
        ("不合格", result.failed_doors),
        ("跳过 / 错误", result.skipped_doors + result.error_doors),
    )
    for column, (label, value) in zip(metric_columns, metrics, strict=True):
        column.metric(label, value)

    _render_result_table(build_result_table_rows(result))
    st.subheader("逐门依据与说明")
    for item in result.results:
        _render_result_detail(item)

    st.download_button(
        "下载完整审计结果（JSON）",
        data=result.model_dump_json(indent=2),
        file_name=f"{Path(result.source_filename).stem}_door_review.json",
        mime="application/json",
        use_container_width=True,
        key="download_review_json_button",
    )


def _render_result_table(rows: Sequence[Mapping[str, Any]]) -> None:
    widths = (1.3, 1.1, 1.15, 1.15, 0.8, 0.75, 0.75, 0.8)
    headings = (
        "门 ID",
        "OverallWidth",
        "实际净宽",
        "规范阈值",
        "检查结果",
        "T3 复用",
        "T4 复用",
        "状态",
    )
    header = st.columns(widths, gap="small")
    for column, heading in zip(header, headings, strict=True):
        column.markdown(f"**{heading}**")
    for row in rows:
        columns = st.columns(widths, gap="small", vertical_alignment="center")
        columns[0].markdown(f"`{row['door_id']}`")
        columns[1].write(_format_mm(row["overall_width_mm"]))
        columns[2].write(_format_mm(row["actual_clear_width_mm"]))
        columns[3].write(_format_mm(row["required_clear_width_mm"]))
        columns[4].write(str(row["result"]))
        columns[5].write("是" if row["t3_reused"] else "否")
        columns[6].write("是" if row["t4_reused"] else "否")
        columns[7].write(str(row["status"]))
        st.markdown("<div class='candidate-divider'></div>", unsafe_allow_html=True)


def _render_result_detail(item: DoorReviewResult) -> None:
    title_result = item.display_result or _status_label(item.status)
    with st.expander(f"{item.door_id} · {title_result}"):
        if item.detailed_reason:
            st.write(item.detailed_reason)
        if item.error:
            st.error(item.error)
        if item.evidence_ids:
            st.caption("证据 ID")
            for evidence_id in item.evidence_ids:
                st.code(evidence_id, language=None)
        else:
            st.caption("没有可展示的证据 ID。")


def _return_to_confirmation() -> None:
    st.session_state["review_selection"] = None
    st.session_state["review_result"] = None
    st.rerun()


def _status_label(status: DoorReviewStatus) -> str:
    return {
        DoorReviewStatus.COMPLETED: "已完成",
        DoorReviewStatus.SKIPPED: "已跳过",
        DoorReviewStatus.ERROR: "错误",
    }[status]


def _format_mm(value: object) -> str:
    if value is None:
        return "—"
    numeric = float(value)
    return f"{numeric:g} mm"


def _coerce_checkbox(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise ValueError("加入后续检查字段必须是勾选或未勾选状态。")


def _coerce_positive_integer(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name}必须是正整数。")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是正整数。") from exc
    if not numeric.is_integer() or numeric <= 0:
        raise ValueError(f"{field_name}必须是正整数。")
    return int(numeric)


def _remove_controlled_upload(path_value: Any) -> None:
    if not path_value:
        return
    try:
        path = Path(str(path_value)).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if temp_root not in path.parents:
            return
        if not path.parent.name.startswith("bim_agent_upload_"):
            return
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError:
        # A stale temporary upload is harmless and can be reclaimed by the OS.
        return


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #f4f6f8; }
        .block-container { max-width: 1180px; padding-top: 2rem; padding-bottom: 4rem; }
        .hero-card {
            padding: 2.1rem 2.3rem; border-radius: 24px; color: #f8fafc;
            background: linear-gradient(125deg, #132238 0%, #173b57 55%, #176b68 100%);
            box-shadow: 0 18px 45px rgba(15, 35, 55, .17); margin-bottom: 1rem;
        }
        .hero-card h1 { margin: .35rem 0 .55rem; font-size: 2.3rem; letter-spacing: -.03em; }
        .hero-card p { margin: 0; max-width: 780px; color: #d9e6ea; font-size: 1.02rem; }
        .eyebrow { color: #86e1d4; font-weight: 700; letter-spacing: .13em; font-size: .75rem; }
        .step-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: .65rem; margin: 1rem 0 2rem; }
        .step { display: flex; align-items: center; gap: .65rem; padding: .75rem 1rem;
                border-radius: 14px; background: #fff; color: #72808e; border: 1px solid #e2e8ee; }
        .step span { font-size: .72rem; font-weight: 800; }
        .step.active { color: #145e5a; border-color: #8dd7cd; background: #eaf8f5; }
        .file-chip { margin: .5rem 0 1rem; padding: .7rem 1rem; border-radius: 12px;
                     background: #fff; border: 1px solid #dfe7ec; color: #344452; }
        .candidate-divider { border-bottom: 1px solid #e4e9ed; margin: .15rem 0 .45rem; }
        div[data-testid="stMetric"] { background: #fff; border: 1px solid #e2e8ee;
                                      padding: 1rem; border-radius: 16px; }
        div.stButton > button[kind="primary"] { background: #176b68; border-color: #176b68; }
        @media (max-width: 760px) { .step-row { grid-template-columns: 1fr; } .hero-card h1 { font-size: 1.8rem; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="BIM Agent · 疏散门审查",
        page_icon="🏫",
        layout="wide",
    )
    initialize_session_state(st.session_state)
    restore_preparation_from_query(st.session_state)
    _inject_styles()
    preparation = st.session_state.get("preparation")
    selection = st.session_state.get("review_selection")
    if not isinstance(preparation, ReviewPreparation):
        render_header(active_step=1)
        render_upload_module()
    elif not isinstance(selection, ReviewSelection):
        render_header(active_step=2)
        render_preparation_summary(preparation)
        render_door_confirmation_module(preparation)
    else:
        render_header(active_step=3)
        render_preparation_summary(preparation)
        render_selection_ready(preparation, selection)


if __name__ == "__main__":
    main()
