import json
import unittest

import openai

from sglang.srt.hf_transformers_utils import get_tokenizer
from sglang.srt.utils import kill_child_process
from sglang.test.test_utils import MODEL_NAME_FOR_TEST, popen_launch_server


class TestOpenAIServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.model = MODEL_NAME_FOR_TEST
        cls.base_url = f"http://localhost:8157"
        cls.api_key = "sk-123456"
        cls.process = popen_launch_server(
            cls.model, cls.base_url, timeout=300, api_key=cls.api_key
        )
        cls.base_url += "/v1"
        cls.tokenizer = get_tokenizer(MODEL_NAME_FOR_TEST)

    @classmethod
    def tearDownClass(cls):
        kill_child_process(cls.process.pid)

    def run_completion(
        self, echo, logprobs, use_list_input, parallel_sample_num, token_input
    ):
        client = openai.Client(api_key=self.api_key, base_url=self.base_url)
        prompt = "The capital of France is"
        if token_input:
            prompt_input = self.tokenizer.encode(prompt)
            num_prompt_tokens = len(prompt_input)
        else:
            prompt_input = prompt
            num_prompt_tokens = len(self.tokenizer.encode(prompt))

        if use_list_input:
            prompt_arg = [prompt_input, prompt_input]
            num_choices = len(prompt_arg)
            num_prompt_tokens *= 2
        else:
            prompt_arg = prompt_input
            num_choices = 1

        if parallel_sample_num:
            # FIXME: This is wrong. We should not count the prompt tokens multiple times for
            # parallel sampling.
            num_prompt_tokens *= parallel_sample_num

        response = client.completions.create(
            model=self.model,
            prompt=prompt_arg,
            temperature=0,
            max_tokens=32,
            echo=echo,
            logprobs=logprobs,
            n=parallel_sample_num,
        )

        assert len(response.choices) == num_choices * parallel_sample_num

        if echo:
            text = response.choices[0].text
            assert text.startswith(prompt)

        if logprobs:
            assert response.choices[0].logprobs
            assert isinstance(response.choices[0].logprobs.tokens[0], str)
            assert isinstance(response.choices[0].logprobs.top_logprobs[1], dict)
            ret_num_top_logprobs = len(response.choices[0].logprobs.top_logprobs[1])
            # FIXME: Sometimes, some top_logprobs are missing in the return value. The reason is that some out_put id maps to the same output token and duplicate in the map
            # assert ret_num_top_logprobs == logprobs, f"{ret_num_top_logprobs} vs {logprobs}"
            assert ret_num_top_logprobs > 0
            if echo:
                assert response.choices[0].logprobs.token_logprobs[0] == None
            else:
                assert response.choices[0].logprobs.token_logprobs[0] != None

        assert response.id
        assert response.created
        assert (
            response.usage.prompt_tokens == num_prompt_tokens
        ), f"{response.usage.prompt_tokens} vs {num_prompt_tokens}"
        assert response.usage.completion_tokens > 0
        assert response.usage.total_tokens > 0

    def run_completion_stream(self, echo, logprobs, token_input):
        client = openai.Client(api_key=self.api_key, base_url=self.base_url)
        prompt = "The capital of France is"
        if token_input:
            prompt_arg = self.tokenizer.encode(prompt)
        else:
            prompt_arg = prompt
        generator = client.completions.create(
            model=self.model,
            prompt=prompt_arg,
            temperature=0,
            max_tokens=32,
            echo=echo,
            logprobs=logprobs,
            stream=True,
        )

        first = True
        for response in generator:
            if logprobs:
                assert response.choices[0].logprobs
                assert isinstance(response.choices[0].logprobs.tokens[0], str)
                if not (first and echo):
                    assert isinstance(
                        response.choices[0].logprobs.top_logprobs[0], dict
                    )
                    ret_num_top_logprobs = len(
                        response.choices[0].logprobs.top_logprobs[0]
                    )
                    # FIXME: Sometimes, some top_logprobs are missing in the return value. The reason is that some out_put id maps to the same output token and duplicate in the map
                    # assert ret_num_top_logprobs == logprobs, f"{ret_num_top_logprobs} vs {logprobs}"
                    assert ret_num_top_logprobs > 0

            if first:
                if echo:
                    assert response.choices[0].text.startswith(
                        prompt
                    ), f"{response.choices[0].text} and all args {echo} {logprobs} {token_input} {first}"
                first = False

            assert response.id
            assert response.created
            assert response.usage.prompt_tokens > 0
            assert response.usage.completion_tokens > 0
            assert response.usage.total_tokens > 0

    def run_chat_completion(self, logprobs, parallel_sample_num):
        client = openai.Client(api_key=self.api_key, base_url=self.base_url)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant"},
                {"role": "user", "content": "What is the capital of France?"},
            ],
            temperature=0,
            max_tokens=32,
            logprobs=logprobs is not None and logprobs > 0,
            top_logprobs=logprobs,
            n=parallel_sample_num,
        )
        if logprobs:
            assert isinstance(
                response.choices[0].logprobs.content[0].top_logprobs[0].token, str
            )

            ret_num_top_logprobs = len(
                response.choices[0].logprobs.content[0].top_logprobs
            )
            assert (
                ret_num_top_logprobs == logprobs
            ), f"{ret_num_top_logprobs} vs {logprobs}"
        assert len(response.choices) == parallel_sample_num
        assert response.choices[0].message.role == "assistant"
        assert isinstance(response.choices[0].message.content, str)
        assert response.id
        assert response.created
        assert response.usage.prompt_tokens > 0
        assert response.usage.completion_tokens > 0
        assert response.usage.total_tokens > 0

    def run_chat_completion_stream(self, logprobs):
        client = openai.Client(api_key=self.api_key, base_url=self.base_url)
        generator = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant"},
                {"role": "user", "content": "What is the capital of France?"},
            ],
            temperature=0,
            max_tokens=32,
            logprobs=logprobs is not None and logprobs > 0,
            top_logprobs=logprobs,
            stream=True,
        )

        is_first = True
        for response in generator:
            data = response.choices[0].delta
            if is_first:
                data.role == "assistant"
                is_first = False
                continue

            if logprobs:
                assert response.choices[0].logprobs
                assert isinstance(
                    response.choices[0].logprobs.content[0].top_logprobs[0].token, str
                )
                assert isinstance(
                    response.choices[0].logprobs.content[0].top_logprobs, list
                )
                ret_num_top_logprobs = len(
                    response.choices[0].logprobs.content[0].top_logprobs
                )
                assert (
                    ret_num_top_logprobs == logprobs
                ), f"{ret_num_top_logprobs} vs {logprobs}"

            assert isinstance(data.content, str)
            assert response.id
            assert response.created

    def test_completion(self):
        for echo in [False, True]:
            for logprobs in [None, 5]:
                for use_list_input in [True, False]:
                    for parallel_sample_num in [1, 2]:
                        for token_input in [False, True]:
                            self.run_completion(
                                echo,
                                logprobs,
                                use_list_input,
                                parallel_sample_num,
                                token_input,
                            )

    def test_completion_stream(self):
        # parallel sampling adn list input are not supported in streaming mode
        for echo in [False, True]:
            for logprobs in [None, 5]:
                for token_input in [False, True]:
                    self.run_completion_stream(echo, logprobs, token_input)

    def test_chat_completion(self):
        for logprobs in [None, 5]:
            for parallel_sample_num in [1, 2]:
                self.run_chat_completion(logprobs, parallel_sample_num)

    def test_chat_completion_stream(self):
        for logprobs in [None, 5]:
            self.run_chat_completion_stream(logprobs)

    def test_regex(self):
        client = openai.Client(api_key=self.api_key, base_url=self.base_url)

        regex = (
            r"""\{\n"""
            + r"""   "name": "[\w]+",\n"""
            + r"""   "population": [\d]+\n"""
            + r"""\}"""
        )

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant"},
                {"role": "user", "content": "Introduce the capital of France."},
            ],
            temperature=0,
            max_tokens=128,
            extra_body={"regex": regex},
        )
        text = response.choices[0].message.content

        try:
            js_obj = json.loads(text)
        except (TypeError, json.decoder.JSONDecodeError):
            print("JSONDecodeError", text)
            raise
        assert isinstance(js_obj["name"], str)
        assert isinstance(js_obj["population"], int)


if __name__ == "__main__":
    unittest.main(warnings="ignore")

    # t = TestOpenAIServer()
    # t.setUpClass()
    # t.test_completion()
    # t.tearDownClass()
