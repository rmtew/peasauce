"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2017 Richard Tew
    Licensed using the MIT license.
"""

import threading
import traceback


class WorkState(object):
    completeness = 0.0
    description = "[set a description]"
    cancelled = False

    def get_completeness(self): return self.completeness
    def set_completeness(self, f): self.completeness = f
    def get_description(self): return self.description
    def set_description(self, s): self.description = s
    def cancel(self): self.cancelled = True
    def is_cancelled(self): return self.cancelled
    def check_exit_update(self, f, s): self.set_completeness(f); self.set_description(s); return self.cancelled


class WorkerThread(threading.Thread):
    def __init__(self, *args, **kwargs):
        super(WorkerThread, self).__init__(*args, **kwargs)

        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)

        self.quit = False
        self.work_data = []

    def stop(self):
        self.lock.acquire()
        self.quit = True
        self.work_data = []
        self.condition.notify()
        self.lock.release()
        #self.wait() # Wait until thread execution has finished.

    def add_work(self, _callable, *_args, **_kwargs):
        self.lock.acquire()
        completed_event = threading.Event()
        completed_event.result = None
        self.work_data.append((_callable, _args, _kwargs, completed_event))

        if not self.is_alive():
            self.start()
        else:
            self.condition.notify()
        self.lock.release()
        return completed_event

    def run(self):
        self.lock.acquire()
        work_data = self.work_data.pop(0)
        self.lock.release()

        while not self.quit:
            completed_event = work_data[3]
            try:
                try:
                    completed_event.result = work_data[0](*work_data[1], **work_data[2])
                    completed_event.set()
                except Exception:
                    traceback.print_stack()
                    raise
            except SystemExit:
                traceback.print_exc()
                raise
            work_data = None

            self.lock.acquire()
            # Wait for the next piece of work.
            if not len(self.work_data):
                self.condition.wait()
            if not self.quit:
                work_data = self.work_data.pop(0)
            self.lock.release()




