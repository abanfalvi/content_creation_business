from dotenv import load_dotenv
import uuid
from typing import Optional
from langchain.tools import tool, ToolRuntime

from .state import LLExtractorState

load_dotenv()


class LessonsLearnedExtracterAgentTools:

    @tool
    def save_learnable_traces(success_trace: bool, title: str, description: str, content: Optional[str], avoid: Optional[str], prefer: Optional[str], runtime: ToolRuntime[None, LLExtractorState]):
        """
        Store both positive and undesired exemplary traces that can be used for improving the specialist agents
        
        Args:
        book_title: str = name of the book that is being processed
        success_trace: bool = whether the current input is to reinforce a behaviour (True) or serve as a negative example (False)
        title: str = a concise summary of the core strategy (e.g., "Navigating Multi-Step Search Filters")
        description: str = one-sentence overview of the item's purpose
        content: str = detailed reasoning steps, decision rationales, and operational insights extracted from past experiences (Use this for desired steps that should be reinforced)
        avoid: str = description of what should be avoided and when (Use this only when you want to add undesired trace)
        prefer: str = description of what should be done instead of the behaviour that should be avoided (Use this only when you want to add undesired trace)

        Output:
        Confirmation that your input has been saved to the persistent local store.
        """
        if success_trace:
            runtime.store.put(("production_traces",), str(uuid.uuid4()), {
                "type": "success",
                "active_agent": "audio_engineer_agent",
                "Title": title, "Description": description, "Content": content,
            })
            return "Successful trace has been saved!"
        else:
            runtime.store.put(("production_traces",), str(uuid.uuid4()), {
                "type": "failure",
                "active_agent": "audio_engineer_agent",
                "Title": title, "Description": description, "Avoid": avoid, "Prefer": prefer
            })
            return "Undesired trace has been saved!"

    @staticmethod
    def extract_learnable_traces(thread_id: str, agent):
        trace = []
        prev_len = 0

        history = list(agent.get_state_history({"configurable": {"thread_id": thread_id}}))
        for snapshot in reversed(history):
            messages = snapshot.values.get("messages", [])
            new_messages = messages[prev_len:]
            prev_len = len(messages)

            for msg in new_messages:
                active_agent = "audio_engineer_agent"
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for call in msg.tool_calls:
                        trace.append({
                            "step": snapshot.metadata["step"],
                            "active_agent": active_agent,
                            "action": "called_tool",
                            "tool": call["name"],
                            "args": call["args"],
                        })
                elif type(msg).__name__ == "ToolMessage":
                    trace.append({
                        "step": snapshot.metadata["step"],
                        "active_agent": active_agent,
                        "action": "tool_result",
                        "content": msg.content,
                    })
                elif type(msg).__name__ == "AIMessage":
                    trace.append({
                        "step": snapshot.metadata["step"],
                        "active_agent": active_agent,
                        "reasoning": "".join(b["reasoning"] for b in msg.content_blocks if b["type"] == "reasoning"),
                        "text": "".join(b["text"] for b in msg.content_blocks if b["type"] == "text"),

                        # "text": msg.text,
                        # "reasoning": msg.reasoning,
                    })
        return trace
