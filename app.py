import argparse
import random
from configparser import ConfigParser
from pprint import pprint
from typing import Mapping

import grpc
from google.protobuf.json_format import MessageToDict
from keycloak import KeycloakOpenID
import speech_recognition as sr
import pyttsx3

import tts_pb2
import tts_pb2_grpc


def read_api_config(file_name: str = "config.ini") -> ConfigParser:

    config = ConfigParser()
    config.read(file_name)

    return config


def get_request_metadata(auth_config: Mapping[str, str]) -> list[tuple[str, str]]:
    sso_connection = KeycloakOpenID(
        auth_config["sso_server_url"],
        auth_config["realm_name"],
        auth_config["client_id"],
        auth_config["client_secret"],
        verify=True,
    )
    token_info = sso_connection.token(grant_type="client_credentials")
    access_token = token_info["access_token"]

    trace_id = str(random.randint(1000, 9999))
    print(f"Trace id: {trace_id}")

    metadata = [
        ("authorization", f"Bearer {access_token}"),
        ("external_trace_id", trace_id),
    ]

    return metadata


def synthesize_file(text: str, api_address: str, auth_config: Mapping[str, str]):
    request = tts_pb2.SynthesizeSpeechRequest(
        text=text,
        encoding=tts_pb2.AudioEncoding.LINEAR_PCM,
        sample_rate_hertz=22050,
        voice_name="gandzhaev",
        synthesize_options=tts_pb2.SynthesizeOptions(
            postprocessing_mode=tts_pb2.SynthesizeOptions.PostprocessingMode.POST_PROCESSING_DISABLE,
            model_type="default",
            voice_style=tts_pb2.VoiceStyle.VOICE_STYLE_NEUTRAL,
        ),
    )
    print("Prepared request:")
    pprint(MessageToDict(request))

    options = [
        ("grpc.min_reconnect_backoff_ms", 1000),
        ("grpc.max_reconnect_backoff_ms", 1000),
        ("grpc.max_send_message_length", -1),
        ("grpc.max_receive_message_length", -1),
    ]

    credentials = grpc.ssl_channel_credentials()

    print(f"\nSending request to gRPC server {api_address}")

    with grpc.secure_channel(
        api_address, credentials=credentials, options=options
    ) as channel:
        stub = tts_pb2_grpc.TTSStub(channel)

        request_metadata = get_request_metadata(auth_config)

        response, call = stub.Synthesize.with_call(
            request,
            metadata=request_metadata,
            wait_for_ready=True,
        )

        print("\nReceived response:")
        initial_metadata = dict(call.initial_metadata())
        print(f"request_id: {initial_metadata.get('request_id', '')}")
        print(f"trace_id: {initial_metadata.get('external_trace_id', '')}")
        print(f"audio: <{len(response.audio)} bytes>")

        path = "synthesized_audio.wav"
        with open(path, "wb") as f:
            f.write(response.audio)

        print(f"Saved received audio to {path}")


# Инициализация распознавания речи и синтеза речи
recognizer = sr.Recognizer()
engine = pyttsx3.init()


def speech_recognition():
    with sr.Microphone() as source:
        print("Скажите что-нибудь...")
        audio = recognizer.listen(source)

        try:
            text = recognizer.recognize_google(audio, language="ru-RU")
            print("Вы сказали:", text)
            return text
        except sr.UnknownValueError:
            print("Не удалось распознать речь")
        except sr.RequestError as e:
            print("Ошибка сервиса распознавания речи; {0}".format(e))

    return None


def text_to_speech(text):
    engine.say(text)
    engine.runAndWait()


# Основной цикл программы
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("text", type=str, help="text for speech synthesis")
    args = parser.parse_args()

    config = read_api_config()

    # Распознавание речи и синтез речи
    while True:
        # Распознавание речи
        recognized_text = speech_recognition()

        # Если распознан текст, синтезировать речь
        if recognized_text:
            synthesize_file(
                recognized_text,
                config["API"]["server_address"],
                config["Auth"],
            )

            # Синтезировать распознанный текст
            text_to_speech(recognized_text)
