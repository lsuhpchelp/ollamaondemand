# =============================
# Ollama OnDemand
# Author: Dr. Jason Li (jasonli3@lsu.edu)
# =============================

import os
import requests
import json
import subprocess
import time
import re
import ollama
import gradio as gr
from arg import get_args
import chatsessions as cs

#======================================================================
#                           Main UI class
#======================================================================

class OllamaOnDemandUI:
    """Ollama OnDemand UI class."""
    
    #------------------------------------------------------------------
    # Constructor
    #------------------------------------------------------------------
    
    def __init__(self, args):
        """
        Constructor.
        
        Input:
            args: Command-line arguments.
        """
        
        # Command-line arguments
        self.args = args
        
        # Stop event (for streaming interruption)
        self.is_streaming = False
        
        # Chat session(s)
        self.update_current_chat(0)                 # Load chat at 0 index. Also initialize:
                                                    #   self.chat_index     - Current chat index
                                                    #   self.chat_title     - Current chat title
                                                    #   self.chat_history   - List of chat (Gradio chatbot compatible)
                                                    #   self.messages       - List of chat (Ollama compatible)
        
        # Start Ollama server and save client(s)
        self.start_server()
        self.client = self.get_client()
        
        # Get model(s)
        self.models = self.get_model_list()
        self.model_selected = self.models[0]
        
        # Read css file
        with open(os.path.dirname(os.path.abspath(__file__))+'/grblocks.css') as f:
            self.css = f.read()

    
    #------------------------------------------------------------------
    # Server connection
    #------------------------------------------------------------------
        
    def start_server(self):
        """Start Ollama Server"""
        
        # Define environment variables
        env = os.environ.copy()
        env["OLLAMA_HOST"] = self.args.ollama_host
        env["OLLAMA_MODELS"] = self.args.ollama_models
        env["OLLAMA_SCHED_SPREAD"] = self.args.ollama_spread_gpu

        # Start the Ollama server
        print("Starting Ollama server on " + self.args.ollama_host)
        process = subprocess.Popen(
            ["ollama", "serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait until the server starts
        for _ in range(60): 
            try:
                if requests.get(self.args.ollama_host).ok:
                    print("Ollama server is running")
                    break
            except:
                pass
            print("Waiting for Ollama server to start...")
            time.sleep(1)
        else:
            raise RuntimeError("Ollama server failed to start in 1 min. Something is wrong.")
            
    def get_client(self, type="ollama"):
        """
        Get client.
        
        Input:
            type: Client type. 
                - "ollama": Ollama client (Default)
                - "langchain": LangChain client (To be added)
        Output:
            client: Client object
        """
        if type=="ollama":
            return ollama.Client(host=self.args.ollama_host)
    
    #------------------------------------------------------------------
    # Misc utilities
    #------------------------------------------------------------------
    
    def get_model_list(self):
        """
        Get list of models.
        
        Input:
            None
        Output: 
            models: List of all model names
        """
        
        models = [model.model for model in self.client.list().models]
        return models if models else ["(No model is found. Create a model to continue...)"]
                    
    def update_current_chat(self, chat_index):
        """
        Update current chat index, history (Gradio), and messages (Ollama) to given index.
        
        Input:
            chat_index:     Chat index (-1 to start a new chat, others to select existings).
        Output: 
            None
        """
        
        if chat_index == -1:
        
            # Update chat index
            self.chat_index = 0
            
            # Create a new chat and update chat history
            self.chat_history = cs.new_chat()
            
            # Get chat title
            self.chat_title = cs.get_chat_title(0)
            
        else:
        
            # Update chat index
            self.chat_index = chat_index
            
            # Update chat history
            self.chat_history = cs.load_chat(chat_index)
            
            # Get chat title
            self.chat_title = cs.get_chat_title(chat_index)
            
        # Update messages
        self.messages = []
        for user, bot in self.chat_history:
            self.messages.append({"role": "user",      "content": user})
            self.messages.append({"role": "assistant", "content": bot})

        
    #------------------------------------------------------------------
    # Event handler
    #------------------------------------------------------------------
    
    def stream_chat(self):
        """
        Stream chat.
        
        Input:
            None
        Output: 
            stream_chat_gr: Gradio function that yields/streams [chatbot, user_input, submit_button_face]
        """
        
        def stream_chat_gr(user_message):

            # Continue only if it is streaming (not interrupted)
            if self.is_streaming:
                
                # Append user message to chat history and messages
                self.chat_history.append((user_message, ""))
                self.messages.append({"role": "user", "content": user_message})

                # Generate next chat results
                response = self.client.chat(
                    model = self.model_selected,
                    messages = self.messages,
                    stream = True
                )

                # Stream results in chunks while not interrupted
                for chunk in response:
                    if not self.is_streaming:
                        break
                    delta = chunk.get("message", {}).get("content", "")
                    delta = delta.replace("<think>", "(Thinking...)").replace("</think>", "(/Thinking...)")
                    self.chat_history[-1] = (user_message, self.chat_history[-1][1] + delta)
                    #cs.chats[self.chat_index] = self.chat_history
                    yield self.chat_history, "", gr.update(value="⏹")
                
                # Add complete AI response to self.messages
                self.messages.append({"role": "assistant", "content": self.chat_history[-1][1]})
            
            self.is_streaming = False
            yield self.chat_history, "", gr.update(value="➤")
        
        return stream_chat_gr
        
    def update_chat_selector(self):
        """
        Update chat selector, mainly for auto-generating a new chat title.
        
        Input:
            None
        Output: 
            chat_selector:  Chat selector update
        """
                
        # If current chat does not have a title, ask client to summarize and generate one.
        if self.chat_title == "":
            
            # Generate a chat title, but do not alter chat_history and messages
            response = self.client.chat(
                model = self.model_selected,
                messages = self.messages + \
                    [ { "role": "user", 
                        "content": "Summarize this entire conversation with less than six words. Be objective and formal (Don't use first person expression). No punctuation."} ],
                stream = False
            )
            
            # Set new title
            new_title = response['message']['content']
            new_title = re.sub(r"<think>.*?</think>", "", new_title, flags=re.DOTALL).strip()
            self.chat_title = new_title
            cs.set_chat_title(self.chat_index, new_title)
            
        return gr.update(choices=cs.get_chat_titles(), value=cs.get_chat_titles()[self.chat_index])
    
    def submit_or_interrupt_event(self):
        """
        Handles the button face of submit / interrupt button.
        
        Input:
            None
        Output: 
            submit_button_face: Gradio update method to update button face ("value" property)
        """
        
        if self.is_streaming:
            self.is_streaming = False
            return gr.update(value="➤")
        else:
            self.is_streaming = True
            return gr.update(value="⏹")
    
    def select_model(self, evt: gr.SelectData):
        """
        Change selected model.
        
        Input:
            evt:            Event instance (as gr.SelectData) 
        Output: 
            None
        """
        self.model_selected = evt.value
            
    def select_chat(self, evt: gr.SelectData):
        """
        Change selected chat.
        
        Input:
            evt:            Event instance (as gr.SelectData) 
        Output: 
            chat_history:   List of chat (Gradio chatbot compatible)
        """
        
        # Update current chat
        self.update_current_chat(evt.index)
        
        # Return chat history to chatbot
        return self.chat_history
        
    # Register New Chat button
    def new_chat(self):
        """
        Change selected chat.
        
        Input:
            None
        Output: 
            chat_selector:  Chat selector update
            chat_history:   List of chat (Gradio chatbot compatible)
        """
        
        # Update current chat
        self.update_current_chat(-1)
        
        # Return updated chat selector and current chat
        return gr.update(choices=cs.get_chat_titles(), value=cs.get_chat_titles()[0]), self.chat_history

    def delete_chat(self):
        """
        Delete the current chat and update UI.
        
        Input:
            None
        Output:
            chat_selector:  Chat selector update
            chat_history:   List of chat (Gradio chatbot compatible)
        """
        
        # Delegate deletion to chatsessions
        cs.delete_chat(self.chat_index)
        
        # Adjust selection: try to select next, else previous, else show blank
        num_chats = len(cs.get_chat_titles())
        if num_chats == 0:
            self.chat_index = 0
            self.chat_history = []
            selector_choices = []
            selector_value = None
        else:
            if self.chat_index >= num_chats:
                self.chat_index = num_chats - 1  # Move to previous if at end
            self.update_current_chat(self.chat_index)
            selector_choices = cs.get_chat_titles()
            selector_value = selector_choices[self.chat_index]
        
        return gr.update(choices=selector_choices, value=selector_value), self.chat_history

    
    
    #------------------------------------------------------------------
    # Build UI
    #------------------------------------------------------------------
    
    def build_ui(self):
        """
        Build UI
        
        Input:
            None
        Output: 
            None
        """

        with gr.Blocks(css=self.css) as self.demo:
            
            #----------------------------------------------------------
            # Create UI
            #----------------------------------------------------------

            gr.Markdown("# Ollama OnDemand")
            
            with gr.Row():
                
                # Left column: Chat Selection
                with gr.Column(scale=1, min_width=220):

                    # New chat and delete chat
                    with gr.Row():
                        
                        # New Chat button
                        new_btn = gr.Button("New Chat")
                        
                        # Delete Chat button
                        del_btn = gr.Button("Delete Chat")
                        
                    # Confirmation "dialog"
                    with gr.Group(visible=False) as del_btn_dialog:
                        gr.Markdown(
                            '<b>Are you sure you want to delete selected chat?</b>', \
                            elem_id="del-button-dialog"
                        )
                        with gr.Row():
                            del_btn_confirm = gr.Button("Yes", variant="stop")
                            del_btn_cancle = gr.Button("Cancel")
                    
                    # Chat selector
                    chat_selector = gr.Radio(
                        choices=cs.get_chat_titles(),
                        show_label=False,
                        type="index",
                        value=cs.get_chat_titles()[0], 
                        interactive=True,
                        elem_id="chat-selector"
                    )
                    
                # Right column: Chat UI
                with gr.Column(scale=3, min_width=400):
                    
                    # Model selector
                    model_dropdown = gr.Dropdown(
                        choices=self.models,
                        value=self.model_selected,
                        label="Select Model",
                        interactive=True
                    )
                    
                    # Main chatbot
                    chatbot = gr.Chatbot()
                    
                    # User input textfield and buttons
                    with gr.Row():
                        
                        user_input = gr.Textbox(placeholder="Type your message here…", show_label=False)
                        submit_btn = gr.Button(value="➤", elem_id="icon-button", interactive=True)
            
            #----------------------------------------------------------
            # Register listeners
            #----------------------------------------------------------
            
            # New chat button
            new_btn.click(
                fn=self.new_chat,
                inputs=[],
                outputs=[chat_selector, chatbot]
            )

            # Delete chat button (along with confirmation dialog)
            del_btn.click(                          # Delete button: Toggle Confirmation dialog
                lambda: gr.update(visible=True),
                inputs=[],
                outputs=[del_btn_dialog]
            )
            del_btn_confirm.click(                  # Confirm delete: Do it and hide dialog
                fn=self.delete_chat,
                inputs=[],
                outputs=[chat_selector, chatbot]
            ).then(
                lambda: gr.update(visible=False),
                inputs=[],
                outputs=[del_btn_dialog]
            )                                       # Cancel delete: Hide dialog
            del_btn_cancle.click(
                lambda: gr.update(visible=False),
                inputs=[],
                outputs=[del_btn_dialog]
            )
            
            # Chat selector
            chat_selector.select(
                fn=self.select_chat,
                inputs=[],
                outputs=[chatbot]
            )
            
            # Model selector
            model_dropdown.select(
                fn=self.select_model,
                inputs=[],
                outputs=[],
            )
            
            # User input textfield and buttons
            user_input.submit(
                fn=self.submit_or_interrupt_event,  # First change submit/interrupt button
                inputs=[],
                outputs=[submit_btn]
            ).then(
                fn=self.stream_chat(),              # Then stream chat
                inputs=[user_input],
                outputs=[chatbot, user_input, submit_btn]
            ).then(
                fn=self.update_chat_selector,       # Then update chat title if needed
                inputs=[],
                outputs=[chat_selector]
            )
            submit_btn.click(
                fn=self.submit_or_interrupt_event,  # First change submit/interrupt button
                inputs=[],
                outputs=[submit_btn]
            ).then(
                fn=self.stream_chat(),              # Then stream chat
                inputs=[user_input],
                outputs=[chatbot, user_input, submit_btn]
            ).then(
                fn=self.update_chat_selector,       # Then update chat title if needed
                inputs=[],
                outputs=[chat_selector]
            )

            #----------------------------------------------------------
            # Load UI
            #----------------------------------------------------------
            
            self.demo.load(
                fn=lambda : cs.load_chat(0),
                inputs=[],
                outputs=[chatbot]
            )
    
    def launch(self):
        """
        Launch UI after it is built.
        
        Input:
            None
        Output: 
            None
        """
        
        self.demo.launch(
            server_name=self.args.host,
            server_port=self.args.port,
            root_path=self.args.root_path
        )


def main():
    
    app = OllamaOnDemandUI(get_args())
    app.build_ui()
    app.launch()

if __name__ == "__main__":
    main()
    