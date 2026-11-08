from openrouter import OpenRouter
from dotenv import load_dotenv
import os

load_dotenv()


class VoiceAgentsTools:

    @staticmethod
    def generate_audio(speech_input: str, voice: str, output_path: str) -> str:
        with OpenRouter(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
        ) as open_router:

            res = open_router.tts.create_speech(input=speech_input, model="fish-audio/s2.1-pro-free:free", response_format="mp3", speed=1, voice=voice)
            res.read()

            with open(output_path, "wb") as f:
                f.write(res.content)
        return output_path
