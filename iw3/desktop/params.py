"""Parameters that can be changed while iw3.desktop is running (hotkeys in the Local Viewer)."""

from typing import NamedTuple


class AdjustableParam(NamedTuple):
    label: str  # shown in the viewer OSD / title
    step: float  # change per key press
    min: float
    max: float
    decimals: int  # rounding of the stored value


ADJUSTABLE_PARAMS: dict[str, AdjustableParam] = {
    "divergence": AdjustableParam("3D Strength", 0.1, 0.0, 10.0, 1),
    "convergence": AdjustableParam("Convergence", 0.1, 0.0, 1.0, 2),
    "foreground_scale": AdjustableParam("Foreground Scale", 0.5, -3.0, 3.0, 1),
}


def format_param_value(name: str, value: float) -> str:
    return f"{value:.{ADJUSTABLE_PARAMS[name].decimals}f}"
