import threading

class Task:
  def __init__(self, task_code, *args):
    self.task_code = task_code
    self.args = args
  
  def run(self):
    self.task_code(*self.args)
    self.task_code = None
    self.args = None

class TaskRunner:
  def __init__(self, tab):
    self.tab = tab
    self.tasks = []
    self.condition = threading.Condition()

  def schedule_task(self, task):
    # with self.condition:
    #   self.tasks.append(task)
    #   self.condition.notify_all()

    self.condition.acquire(blocking=True)
    self.tasks.append(task)
    self.condition.notify_all()
    self.condition.release()

  def run(self):
    """Blocking loop: used by the background task-runner thread."""
    while True:
      task = None
      self.condition.acquire(blocking=True)
      if len(self.tasks) > 0:
        task = self.tasks.pop(0)  # pop from front, not back
      self.condition.release()
      if task:
        task.run()

      self.condition.acquire(blocking=True)
      if len(self.tasks) == 0:
        self.condition.wait()
      self.condition.release()


