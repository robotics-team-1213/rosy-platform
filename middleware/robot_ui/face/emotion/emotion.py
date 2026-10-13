import rclpy
from rclpy.node import Node
from ament_index_python.packages import get_package_share_directory
from PIL import Image, ImageSequence
import os
import threading
from interfaces.srv import Emotion
from .rosy_lcd import LCD

class RosyEmotion(Node):
    def __init__(self):
        super().__init__('emotion')

        self.emotion_path = os.path.join(get_package_share_directory('emotion'), 'emotion')
        self.emotion_service = self.create_service(Emotion, 'set_emotion', self.set_emotion_callback)
        self.lcd = LCD()
        self.get_logger().info(f"Rosy's emotion server is ready!!")

    def lcd_callback(self, request, response):
        emo = request.emotion
        self.get_logger().info(f"Rosy's emotion set to {emo}")
        response.response = f"Rosy's emotion set to {emo}"
        
        if emo == "hello":
            self.play_gif(self.emotion_path + "/hello.gif")
        
        elif emo == "basic":
            self.play_gif(self.emotion_path + "/basic.gif")
        
        elif emo == "angry":
            self.play_gif(self.emotion_path + "/angry.gif")
        
        elif emo == "bored":
            self.play_gif(self.emotion_path + "/bored.gif")

        elif emo == "fun":
            self.play_gif(self.emotion_path + "/fun.gif")
            
        elif emo == "happy":
            self.play_gif(self.emotion_path + "/happy.gif")

        elif emo == "interest":
            self.play_gif(self.emotion_path + "/interest.gif")

        elif emo == "sad":
            self.play_gif(self.emotion_path + "/sad.gif")

        else:
            response.response = "Wrong command or emotion not cached"
            self.get_logger().warn(f"Emotion '{emo}' not found in cache.")

        return response

    def play_gif(self, path):
        img = Image.open(path)
        for i, frame in enumerate(ImageSequence.Iterator(img)):
            if i % 2 == 0:
                self.lcd.img_show(frame)


def main(args=None):
    rclpy.init(args=args)
    emotion_node = RosyEmotion()
     
    try:
        rclpy.spin(emotion_node)
    except KeyboardInterrupt:
        emotion_node.get_logger().info("KeyboardInterrupt, shutting down.")
    finally:
        emotion_node.lcd.clear()
        emotion_node.destroy_node()
        rclpy.shutdown()
 
if __name__ == '__main__':
    main()