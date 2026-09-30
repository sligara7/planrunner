"""Facility PVs the plans read that the blackhole can only fake as bare zeros.

* **Shutters.** hextools' ``Shutter`` reads ``Pos-Sts`` as an enum (``Open`` /
  ``Not Open``) and waits for it to change after writing ``Cmd:Opn-Cmd`` or
  ``Cmd:Cls-Cmd``. A fabricated PV is a plain number that never moves, so the
  device refuses to connect and every shutter step would time out. Served here as
  a small state machine: a command moves the readback after ``SETTLE_S``.
  Legacy ophyd readers (hex-profile-collection's ``fe_shutter_status``) still see
  0 / 1.
* **Ring current.** hextools installs a suspender that holds every plan while
  ``SR:OPS-BI{DCCT:1}I:Real-I`` is under 100 mA; a fabricated 0 would suspend all of
  them. Served as a steady 400 mA.

Composed into the unified sim IOC (``sim_ioc.py``) like the detector PV sets.
"""

import asyncio

from caproto import ChannelType
from caproto.server import PVGroup, pvproperty

# prefix -> starts open. The front-end shutter is opened by operators, never by a plan
# (hextools checks it without actuating); the photon shutter is the plan's to open.
SHUTTERS = {"XF:27IDA-PPS{Sh:FE}": True, "XF:27IDA-PPS{L1-S1}": False}
RING_CURRENT_PV = "SR:OPS-BI{DCCT:1}I:Real-I"
RING_CURRENT_MA = 400.0
SETTLE_S = 0.2
_CLOSED, _OPEN = "Not Open", "Open"


def _literal(name: str) -> str:
    """caproto expands ``{...}`` in PV names as macros; NSLS-II names use braces."""
    return name.replace("{", "{{").replace("}", "}}")


class ShutterSim(PVGroup):
    status = pvproperty(name="Pos-Sts", value=_CLOSED, enum_strings=[_CLOSED, _OPEN],
                        dtype=ChannelType.ENUM, read_only=True)
    open_cmd = pvproperty(name="Cmd:Opn-Cmd", value=0)
    close_cmd = pvproperty(name="Cmd:Cls-Cmd", value=0)

    @open_cmd.putter
    async def open_cmd(self, instance, value):
        await self._move(_OPEN)
        return 0

    @close_cmd.putter
    async def close_cmd(self, instance, value):
        await self._move(_CLOSED)
        return 0

    async def _move(self, state: str) -> None:
        await asyncio.sleep(SETTLE_S)
        await self.status.write(state)


class RingSim(PVGroup):
    current = pvproperty(name=_literal(RING_CURRENT_PV), value=RING_CURRENT_MA, read_only=True,
                         units="mA", precision=1)


def build_facility_pvdb() -> tuple[dict, list[PVGroup]]:
    """The PVs, and the groups that own them (keep these alive while serving)."""
    groups: list[PVGroup] = []
    for prefix, is_open in SHUTTERS.items():
        shutter = ShutterSim(prefix=_literal(prefix))
        shutter.status._data["value"] = _OPEN if is_open else _CLOSED
        groups.append(shutter)
    groups.append(RingSim(prefix=""))
    pvdb: dict = {}
    for group in groups:
        pvdb.update(group.pvdb)
    return pvdb, groups
