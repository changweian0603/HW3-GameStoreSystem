import struct
import json
import asyncio
from .consts import MAX_FRAME_SIZE

def _pack(obj):
    """
    Pack a Python object (dict/list/str) into a length-prefixed byte frame.
    Format: [4-byte Big-Endian Length] [UTF-8 JSON Body]
    """
    if isinstance(obj, (dict, list)):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    elif isinstance(obj, str):
        body = obj.encode('utf-8')
    elif isinstance(obj, bytes):
        body = obj
    else:
        body = str(obj).encode('utf-8')

    length = len(body)
    if length > MAX_FRAME_SIZE:
        raise ValueError(f"Frame too large: {length} > {MAX_FRAME_SIZE}")
    
    return struct.pack('!I', length) + body

async def sendf(writer: asyncio.StreamWriter, obj):
    """
    Send a length-prefixed frame.
    """
    if writer.is_closing():
        return
    data = _pack(obj)
    writer.write(data)
    await writer.drain()

async def recvf(reader: asyncio.StreamReader):
    """
    Receive a length-prefixed frame.
    Returns the parsed JSON object (dict/list) or str.
    """
    try:
        raw_len = await reader.readexactly(4)
        length = struct.unpack('!I', raw_len)[0]
        
        if length > MAX_FRAME_SIZE:
            raise ValueError(f"Frame too large: {length}")
        
        body_data = await reader.readexactly(length)
        
        try:
            return json.loads(body_data.decode('utf-8'))
        except json.JSONDecodeError:
            return body_data.decode('utf-8')
            
    except asyncio.IncompleteReadError:
        raise ConnectionResetError("Connection closed by peer")
    except Exception as e:
        raise e
