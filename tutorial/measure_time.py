import time

class MeasureTime:
  def __init__(self):
    self.file = open("browser.trace", "w")
    self.file.write('{"traceEvents": [')
    ts = time.time() * 1000000
    self.file.write(
      '{ "name": "process_name",' +
      '"ph": "M",' +
      '"ts": ' + str(ts) + ',' +
      '"pid": 1, "cat": "__metadata",' +
      '"args": {"name": "Browser"}}')
    
    self.file.flush()

  def time(self, name):
    ts = time.time() * 1000000
    self.file.write(
      ', { "ph": "B", "cat": "_",' +
      '"name": "' + name + '",' +
      '"ts": ' + str(ts) + ',' +
      '"pid": 1, "tid": 1 }')

    self.file.flush()

  def stop(self, name):
    ts = time.time() * 1000000
    self.file.write(
      ', { "ph": "E", "cat": "_",' +
      '"name": "' + name + '",' +
      '"ts": ' + str(ts) + ',' +
      '"pid": 1, "tid": 1 }')

    self.file.flush()

  def finish(self):
    self.file.write(']}')
    self.file.close()

