from SimpleHTTPServer import SimpleHTTPRequestHandler
from BaseHTTPServer import HTTPServer
from SocketServer import ThreadingMixIn
import urlparse
import threading
from contextlib import contextmanager


@contextmanager
def get_temp_filename(*args, **kwargs):
  import tempfile
  import os
  of, filename = tempfile.mkstemp(*args, **kwargs)
  os.close(of)
  try:
    yield filename
  finally:
    os.remove(filename)


if not 'TMSHandler' in globals():

  class TMSHandler(SimpleHTTPRequestHandler):

    def log_request(self, code=None, size=None):
      pass


def do_GET(self):
  import numpy as np
  import cv

  parsed_path = urlparse.urlparse(self.path)
  # I'm going to assume that the format is /{z}/{x}/{y}.jpg,
  # if that changes then we need to fix this expression
  z, x, y = [int(_) for _ in parsed_path.path.split('.')[0].split('/')[1:]]

  im = np.zeros((256, 256, 3), 'u1')
  s = 'x:%d y:%d zoom:%d' % (x, y, z)
  cv.PutText(im, s, (80, 100),
      cv.InitFont(cv.CV_FONT_HERSHEY_SIMPLEX, 0.5, 0.5), (255, 255, 0))

  with get_temp_filename('.jpg') as filename:
    cv.SaveImage(filename, im)

    self.send_response(200)
    self.end_headers()
    with open(filename, 'r') as f:
      self.wfile.write(f.read())
  return
TMSHandler.do_GET = do_GET


if not 'server' in globals():

  class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass

  server = ThreadedHTTPServer(('localhost', 8080), TMSHandler)
  threading.Thread(target=server.serve_forever).start()
  print 'serving'
