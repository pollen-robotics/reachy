"""WebSocket IO definition."""

import json
import asyncio
import websockets
import numpy as np

from threading import Thread, Event
from base64 import b64decode
from io import BytesIO
from PIL import Image

from .io import IO


class WsIO(IO):
    """WebSocket IO implementation."""

    ws = None

    def __init__(self, part_name):
        """Init an io attached to the given part."""
        self.part_name = part_name
        self.motors = []

    @classmethod
    def shared_server(cls, part_name):
        """Create a new io with its ws server."""
        io = cls(part_name)

        if cls.ws is None:
            cls.ws = WsServer()
            cls.ws.run_in_background()
        cls.ws.register(io)

        return io

    def find_module(self, module_name):
        """Get a specific module from the IO.

        For the moment no module are really implemented. Only placeholders for code compatibility are provided.
        """
        if module_name == 'force_gripper':
            return WsFakeForceSensor()

        raise NotImplementedError

    def find_dxl(self, dxl_name, dxl_config):
        """Get a specific dynamixel motor from the IO.

        Only goal position is used atm.
        """
        pos = dxl_config['offset'] * (-1 if dxl_config['orientation'] == 'indirect' else 1)
        m = WsMotor(name=f'{self.part_name}.{dxl_name}', initial_position=pos)
        self.motors.append(m)
        self.ws.motors[m.name] = m
        return m

    def find_orbita_disks(self):
        """Get a specific orbita module from the IO.

        Not currently supported.
        """
        bottomOrb = WsFakeOrbitaDisk()
        middleOrb = WsFakeOrbitaDisk()
        topOrb = WsFakeOrbitaDisk()
        return [bottomOrb, middleOrb, topOrb]

    def attach_camera(self, camera_id):
        """Return a camera associated to the specified id."""
        cam = WsCamera()
        self.ws.cam = cam
        return cam

    def close(self):
        """Close the WS."""
        self.ws.close()


class WsMotor(object):
    """Motor Placeholder.

    Only the goal position (ie. target_rot_position) is currently used.
    """

    def __init__(self, name, initial_position):
        """Init the fake motor."""
        self.name = name

        self.compliant = False
        self.target_rot_position = initial_position
        self.rot_position = initial_position


class WsFakeOrbitaDisk(object):
    """Orbital disk placeholder."""

    def __init__(self):
        """Create fake Orbita disk."""
        self.compliant = False
        self.target_rot_position = 0
        self.limit_current = 0
        self.encoder_res = 0
        self.reduction = 0
        self.wheel_size = 0
        self.positionPid = 0
        self.rot_position_mode = True
        self.rot_speed_mode = False
        self.rot_position = True
        self.rot_speed = False

    def setToZero(self):
        """Do nothing atm."""
        pass


class WsFakeForceSensor(object):
    """Force Sensor placeholder.

    Always return a nan as force.
    """

    def __init__(self):
        """Init the fake force sensor."""
        self.load = np.nan


class WsCamera(object):
    """Remote Camera."""

    def __init__(self):
        """Set remote camera up."""
        self.frame = np.zeros((300, 480, 3), dtype=np.uint8)

    def read(self):
        """Get latest received frame."""
        return True, self.frame

    def close(self):
        """Close the camera."""
        pass


class WsServer(object):
    """WebSocket server, sync value from the modules with their equivalent from the client."""

    def __init__(self, host='0.0.0.0', port=6171):
        """Prepare the ws server."""
        self.host, self.port = host, port
        self.running = Event()

        self.parts = []
        self.motors = {}

    async def sync(self, websocket, path):
        """Sync loop that exchange modules state with the client."""
        self.running.set()

        while self.running.is_set():
            if not websocket.open:
                break

            msg = json.dumps({
                'motors': [
                    {'name': m.name, 'goal_position': m.target_rot_position}
                    for m in sum([p.motors for p in self.parts], [])
                ]
            })
            await websocket.send(msg.encode('UTF-8'))

            resp = await websocket.recv()
            state = json.loads(resp)

            jpeg_data = b64decode(state['left_eye'])
            self.cam.frame = np.array(Image.open(BytesIO(jpeg_data)))

            for m in state['motors']:
                self.motors[m['name']].rot_position = m['present_position']

    def close(self):
        """Stop the sync loop."""
        self.running.clear()
        self.t.join()

    def register(self, io):
        """Register a new io (and its module) to be synced."""
        self.parts.append(io)

    def run_forever(self):
        """Run the sync loop forever."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        serve = websockets.serve(self.sync, self.host, self.port)

        loop.run_until_complete(serve)
        loop.run_forever()

    def run_in_background(self):
        """Run the sync loop forever in background."""
        self.t = Thread(target=self.run_forever)
        self.t.daemon = True
        self.t.start()
