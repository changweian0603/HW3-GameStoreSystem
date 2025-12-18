import asyncio, json, struct, sys, argparse, os, tkinter as tk

def _pack(obj):
    body = json.dumps(obj).encode('utf-8')
    return struct.pack('!I', len(body)) + body

async def sendf(writer, obj):
    writer.write(_pack(obj))
    await writer.drain()

async def recvf(reader):
    raw = await reader.readexactly(4)
    n = struct.unpack('!I', raw)[0]
    data = await reader.readexactly(n)
    return json.loads(data.decode('utf-8'))

class ClickerGUI:
    def __init__(self, loop, args):
        self.loop = loop
        self.args = args
        self.writer = None
        
        self.root = tk.Tk()
        self.root.title("Multi Clicker")
        self.root.geometry("400x300")
        
        self.lbl_info = tk.Label(self.root, text="Waiting...", font=("Arial", 14))
        self.lbl_info.pack(pady=10)
        
        self.btn_click = tk.Button(self.root, text="CLICK ME!", font=("Arial", 20, "bold"), command=self.on_click, bg="red", fg="white")
        self.btn_click.pack(pady=20, fill="x", padx=20)
        
        self.lbl_scores = tk.Label(self.root, text="", font=("Courier", 12), justify="left")
        self.lbl_scores.pack(pady=10)
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_handler)
        self.loop.create_task(self.connect())

    def on_click(self):
        if self.writer:
            self.loop.create_task(sendf(self.writer, {"type": "CLICK"}))

    async def connect(self):
        try:
            reader, writer = await asyncio.open_connection(self.args.host, self.args.port)
            self.writer = writer
            
            # Auth
            writer.write((json.dumps({"type": "AUTH", "token": self.args.token}) + "\n").encode())
            await writer.drain()
            
            line = await reader.readline()
            if json.loads(line.decode()).get("status") != "OK":
                self.lbl_info.config(text="Auth Failed")
                return

            self.lbl_info.config(text="Connected!")
            
            while True:
                msg = await recvf(reader)
                t = msg.get("type")
                if t == "WELCOME":
                    self.lbl_info.config(text=f"You are {msg['my_id']}")
                elif t == "UPDATE":
                    scores = msg.get("scores", {})
                    txt = "Scores:\n" + "\n".join([f"{k}: {v}" for k, v in scores.items()])
                    self.lbl_scores.config(text=txt)
                elif t == "WINNER":
                    self.lbl_info.config(text=f"Winner: {msg['winner']}!")

        except Exception as e:
            print(e)
            try:
                self.lbl_info.config(text="Disconnected")
            except: pass
        finally:
            self.on_close_handler()

    async def on_close(self):
        try: 
            if self.writer: self.writer.close()
        except: pass
        try:
            self.root.destroy()
        except: pass
        os._exit(0)

    def on_close_handler(self):
        self.loop.create_task(self.on_close())
    
def run(args):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = ClickerGUI(loop, args)
    
    async def tk_loop():
        while True:
            try:
                app.root.update()
                await asyncio.sleep(0.01)
            except: 
                break
        
        loop.stop()
        os._exit(0)
    
    try: loop.run_until_complete(tk_loop())
    except: pass
    os._exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--room-id", required=True)
    args = parser.parse_args()
    
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    run(args)
