"""Typed, hard-bounded model-visible ForgeOS input."""

from dataclasses import dataclass

MODEL_ITEM_BYTE_LIMIT = 900
MODEL_INPUT_BYTE_LIMIT = 9_000
RUNTIME_CONTEXT_BYTE_LIMIT = 2_700
TRUNCATION_MARKER = "\n[TRUNCATED BY FORGEOS]"


@dataclass(frozen=True, slots=True)
class ModelTextItem:
    """One independently bounded text item submitted through the SDK."""

    label: str
    text: str

    @classmethod
    def create(cls, label: str, text: str) -> "ModelTextItem":
        return cls(
            label=label,
            text=bounded_model_text(text, maximum_bytes=MODEL_ITEM_BYTE_LIMIT),
        )


@dataclass(frozen=True, slots=True)
class ModelInput:
    """A bounded collection of typed text items for one Codex turn."""

    items: tuple[ModelTextItem, ...]

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("model input must contain at least one item")
        if any(len(item.text.encode("utf-8")) > MODEL_ITEM_BYTE_LIMIT for item in self.items):
            raise ValueError("model input item exceeds byte limit")
        if self.total_bytes > MODEL_INPUT_BYTE_LIMIT:
            raise ValueError("model input exceeds total byte limit")

    @property
    def total_bytes(self) -> int:
        return sum(len(item.text.encode("utf-8")) for item in self.items)

    def canonical_bytes(self) -> bytes:
        return b"\x1e".join(
            item.label.encode("utf-8") + b"\x1f" + item.text.encode("utf-8") for item in self.items
        )

    def texts(self) -> tuple[str, ...]:
        return tuple(item.text for item in self.items)


def bounded_model_text(value: str, *, maximum_bytes: int) -> str:
    """Bound UTF-8 text below Codex's 10K-token per-item ceiling.

    A byte ceiling is conservative: byte-fallback tokenization cannot produce
    more tokens than UTF-8 bytes. This keeps the guarantee independent of the
    model's tokenizer version.
    """

    if maximum_bytes <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    marker = TRUNCATION_MARKER.encode("utf-8")
    prefix = encoded[: max(0, maximum_bytes - len(marker))]
    while prefix:
        try:
            return prefix.decode("utf-8") + TRUNCATION_MARKER
        except UnicodeDecodeError:
            prefix = prefix[:-1]
    return marker[:maximum_bytes].decode("utf-8", errors="ignore")


def assemble_turn_input(
    *,
    task_id: str,
    title: str,
    objective: str,
    acceptance_criteria: tuple[str, ...],
    constraints: tuple[str, ...],
    runtime_items: tuple[ModelTextItem, ...],
    custom_prompt: str | None,
) -> ModelInput:
    """Preserve every task section as its own bounded SDK text item."""

    items: list[ModelTextItem] = []
    if custom_prompt is not None and custom_prompt.strip():
        items.append(ModelTextItem.create("turn_instruction", custom_prompt.strip()))
    items.extend(
        (
            _required_contract_item(
                "task_header",
                f"ForgeTask {task_id}: {title}. Implement or repair this task in the current "
                "workspace. ForgeOS validates and accepts it independently.",
            ),
            _required_contract_item("task_objective", f"Objective:\n{objective}"),
            _required_contract_item(
                "task_acceptance",
                "Acceptance criteria:\n" + "\n".join(f"- {item}" for item in acceptance_criteria),
            ),
            _required_contract_item(
                "task_constraints",
                "Constraints:\n"
                + ("\n".join(f"- {item}" for item in constraints) or "- None declared"),
            ),
        )
    )
    items.extend(runtime_items)
    return ModelInput(tuple(items))


def _required_contract_item(label: str, text: str) -> ModelTextItem:
    size = len(text.encode("utf-8"))
    if size > MODEL_ITEM_BYTE_LIMIT:
        raise ValueError(
            f"{label} is {size} bytes and exceeds the {MODEL_ITEM_BYTE_LIMIT}-byte model item "
            "limit; split the ForgeTask so its contract can be preserved"
        )
    return ModelTextItem(label=label, text=text)
