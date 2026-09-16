import cv2
from gpiozero import Servo
#from gpiozero.pins.pigpio import PiGPIOFactory
from time import sleep
# ========================
# Face Center Detection
# ========================
# (Sections marked with '# CHANGED' are new or modified)

def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml')

    Kp = 0.05 # proportional gain
    #factory = PiGPIOFactory()
    servo = Servo(17)
    servo.detach()
    sleep(2)
    print("servos initialized")
    n = 0

    print("Press 'q' to quit.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        h, w = frame.shape[:2]
        frame_center_x = w/2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.3, minNeighbors=5, minSize=(30, 30)
        )
        
        servo.detach() # !!!!!!!!!!!!!!!!
        
        for (x, y, w, h) in faces:
            # draw the face rectangle
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # === CHANGED ===
            # compute the center point of the face
            cx = x + w // 2
            cy = y + h // 2

            # === CHANGED ===
            # draw a small circle at the center of the face
            cv2.circle(frame, (cx, cy), 4, (255, 0, 0), -1)

            # === CHANGED ===
            # overlay the center coordinates next to the face
            cv2.putText(
                frame,
                f"({cx},{cy})",
                (cx + 10, cy - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 0, 0),
                1,
                cv2.LINE_AA
            )
            
            # -------- SERVO CONTROL ---------
            #if n >=40:
            error = cx - frame_center_x
            #error_norm = error / frame_center_x
            #command = error_norm * Kp
            
            #command = max(-1.0, min(1.0, command))
            #servo.value = command
            if error > 30:
                servo.value = 0.4
                n=25
            elif error < -30:
                servo.value = -0.4
                n=25
            else:
                servo.detach()

            # === CHANGED ===
            # also print to console
            print(f"Face center at x={cx}, y={cy}")

        cv2.imshow('Face Centers - 320x240', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        n += 1
        sleep(.02)

    cap.release()
    cv2.destroyAllWindows()
    servo.detach()

if __name__ == '__main__':
    main()
