from openrouter import OpenRouter

from podcast_generation.settings import project_path
import os



class VoiceAgentsTools:

    @staticmethod
    def generate_audio(speech_input: str, voice: str, output_path: str) -> str:
        with OpenRouter(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
        ) as open_router:

            res = open_router.tts.create_speech(input=speech_input, model="fish-audio/s2.1-pro-free:free", response_format="mp3", speed=1, voice=voice)
            res.read()

            out = project_path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "wb") as f:
                f.write(res.content)
        return output_path
