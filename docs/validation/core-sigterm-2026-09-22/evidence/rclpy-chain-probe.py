import os, signal, threading, time
hits = []
signal.signal(signal.SIGTERM, lambda s, f: hits.append(s))
import rclpy
rclpy.init()
print("ok before", rclpy.ok())
os.kill(os.getpid(), signal.SIGTERM)
time.sleep(0.2)
print("ok after", rclpy.ok(), "python handler hits", hits)
