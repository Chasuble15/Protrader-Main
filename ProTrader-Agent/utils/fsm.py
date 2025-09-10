# utils/fsm.py
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

OnEnter = Callable[['FSM'], Optional[str]]   # return next_state or None to stay
OnTick  = Callable[['FSM'], Optional[str]]
OnExit  = Callable[['FSM'], None]

@dataclass
class StateDef:
    name: str
    on_enter: Optional[OnEnter] = None
    on_tick:  Optional[OnTick]  = None
    on_exit:  Optional[OnExit]  = None
    timeout_s: Optional[float]  = None        # None = pas de timeout
    on_timeout: Optional[str]   = None        # cible si timeout

@dataclass
class FSM:
    states: Dict[str, StateDef]
    start: str
    end: str = "END"
    error: str = "ERROR"

    current: str = field(init=False)
    _entered_at: float = field(init=False, default=0.0)
    ctx: dict = field(default_factory=dict)   # contexte partagé (résultats vision/OCR, flags, etc.)

    def __post_init__(self):
        if self.start not in self.states:
            raise ValueError("Start state undefined")
        self.current = self.start
        self._entered_at = 0.0

    def _switch(self, next_state: str):
        # exit current state only if it has actually been entered
        # (self._entered_at is set on state entry).
        if self._entered_at and (st := self.states.get(self.current)) and st.on_exit:
            st.on_exit(self)
        # entrer dans le nouveau
        self.current = next_state
        self._entered_at = time.time()
        if (st := self.states.get(self.current)) and st.on_enter:
            nxt = st.on_enter(self)
            if nxt:  # transition immédiate si on_enter renvoie une cible
                self._switch(nxt)

    def run(self, tick_hz: float = 10.0, max_runtime_s: Optional[float] = None):
        self._switch(self.current)  # on_enter du start
        start_ts = time.time()
        period = 1.0 / tick_hz

        while True:
            # fin globale ?
            if self.current == self.end:
                return "SUCCESS"
            if self.current == self.error:
                return "ERROR"
            if max_runtime_s is not None and (time.time() - start_ts) > max_runtime_s:
                self._switch(self.error)
                return "TIMEOUT_GLOBAL"

            st = self.states[self.current]

            # timeout local ?
            if st.timeout_s is not None and (time.time() - self._entered_at) > st.timeout_s:
                if st.on_timeout:
                    self._switch(st.on_timeout)
                else:
                    self._switch(self.error)
                time.sleep(period)
                continue

            # tick
            if st.on_tick:
                nxt = st.on_tick(self)  # peut renvoyer None (rester), ou un nom d'état
                if nxt:
                    self._switch(nxt)

            time.sleep(period)
