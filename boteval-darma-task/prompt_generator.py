
import re
from boteval import log
from multiprocessing import Lock
from multiprocessing.pool import ThreadPool
from typing import List

ROOT_TOKEN_REGEX = '([\w]+)'
TOKEN_REGEX = '<([\w-]+)>'
# Difference is TOKEN_REGEX accepts '-<SOME_FORMAT>'
# which would correspond to middle transformation of value
# such as '-list', which is list format

class Variable:
    """
    A very flexible class used to organize variable/instruction updates 
    and easily extend to trace history or current replacements in tokens.
    """
    def __init__(self, parameters):
        if not isinstance(parameters, dict):
            parameters = { 'instruction': parameters }
        self._parameters = parameters
        self.instruction_raw = self._parameters.get('instruction')
        self._variables = {
            t: None
            for t in re.findall(TOKEN_REGEX, self.instruction_raw)
        }
        self._assign_cnt = 0
        self._assignments = {} # tracking assignments of value
    
    def get_tokens(self): return self._variables.keys()
    
    def replace(self, token: str, value, format: str=None):
        """

        Args:
            token (str): token/key name pointing to  an existing value; however, if new token is given, it will still be forceably added.
            value (_type_): value of assignment/replacement
            format (str, optional): name of the format of the type of value; if not provided then assignment refers to original format of the value. Defaults to None. Defaults to None.
        """
        if format:
            token = f'{token}-{format}'
        self._variables[token] = value
    
    def get(self, name:str, default:str=None):
        return self._parameters.get(name, default)
    
    def __getitem__(self, name: str): return self.get(name)
    
    def __setitem__(self, name: str, val): self._parameters[name] = val
    
    def update(self, _dict: dict): self._parameters.update(_dict)
    
    def get_assignment(self, format: str=None):
        """

        Args:
            format (str, optional): name of the format of the type of value; if not provided then assignment refers to original format of the value. Defaults to None. Defaults to None.

        Returns:
            any: value of assignment
        """
        key = 'value'
        if format:
            key = f'{key}-{format}' 
        return self._parameters[key]
        
    def trace(self) -> str:
        """

        Returns:
            str: debug of insturction with colored format to be printed in console, including assignment count and value of assignment between square brackets inline.
        """
        statement = self.instruction_raw
        decoding_placeholder =\
            "[\033[95m{cnt}\033[00m : \033[96m{decoding}\033[00m]"
        for token, (var, format) in self._variables.items():
            statement = statement.replace(
                f'<{token}>', 
                decoding_placeholder.format(
                    cnt=var._assign_cnt,
                    decoding=var.get_assignment(format=format) 
                )
            )
        return statement

    def __str__(self) -> str:
        statement = self.instruction_raw
        for token, (var, format_) in self._variables.items():
            decoding = var.get_assignment(format=format_)
            statement = statement.replace(
                f'<{token}>', decoding
            )
        return statement

    def is_assignable(self, turn_idx:int) -> bool:
        """
        Args:
            turn_idx (int): globally defined value representing the current turn of the conversation

        Returns:
            bool: indicator whether the variable value can be assigned at current turn or not.
        """
        if self.get('value') is None:
            return True
        if self._assignments.get(turn_idx) is not None:
            return False
        freq = self.get('frequency', turn_idx + 2)
        return ((turn_idx + 1) % freq) == 0
    
    def assign(self, value, turn_idx: int=None, format:str=None):
        """

        Args:
            value (any): value to be assigned
            turn_idx (int, optional): globally defined value representing the current turn of the conversation. requried if arg `format` is not provided Defaults to None.
            format (str, optional): name of the format of the type of value to be assigned; if not provided then assignment refers to original format of the value. Defaults to None.
        """
        if format is not None:
            key = f'value-{format}'
        else:
            # print(f"token [{self.get('id')}] = [{self.get('value') is not None}]")
            key = 'value'
            self._assign_cnt += 1
            self._assignments[turn_idx] = value
        self._parameters[key] = value

        if not value:
            log.error(
                f'Empty Assignment @ => #{self._assign_cnt}: '
                f'{key}({self.get("id")}) = {value}'
            )
        else:
            log.debug(
                f'Assignment #{self._assign_cnt}: '
                f'{key}({self.get("id")}) = {value}'
            )
        
    def backspace(self): 
        """
        Goes back in time one step
        """
        if self._assignments.get(self._assign_cnt):
            self._assignments.__delitem__(self._assign_cnt)
        self._assign_cnt -= 1
        
    def is_constant(self): return not self._variables

class PromptGenerator:
    """
    A class used to adapt to dynamic formulation of persona configuration.
    Dynamic Formulation at the moment means creating embedable instruction
    prompts for a persona while the tokens are based on other pre-processing
    prompts.
    
    Features:
    - Parsing embeddable prompts
    - Post-processing prompts with post-regex, and any # of post-func (lambda functions)
    - Parsing embeddable post-regex; Saving their (TOKEN)-list variable
    - Parsing embeddable post-func
    - API agnostic
    - Multiple endpoints
    - Tracing of recent assignments of variable-tokens per instruction/variable
    - Turn aware variables according to frequency of assigning
    
    TODO make post-processing routines somehow (such as detecting end)

    @author: Basem Rizk
    
    """
    
    def __init__(self, config_json: dict,
                 endpoints: dict,
                 engine: str,
                 few_shot_example=None,
                 default_endpoint='query_lm'):
        """

        Args:
            config_json (dict): JSON formatted persona configuration
            endpoints (dict): dictionary of endpoint function calls including lm call
            few_shot_example (_type_, optional): Not tested but added for backward 
            compatibility. Defaults to None.
            default_endpoint (str, optional): Name of endpoint to a lm call. Defaults 
            to 'query_lm'.
        """
        self.endpoints = endpoints
        self.engine = engine 
        self.default_endpoint = default_endpoint
        self.id = config_json['id']
        self.notes = config_json['notes']
        self.title = config_json['title']    
        self.instruction = Variable({
            "instruction": config_json['instruction']
        })
        self.few_shot_example = few_shot_example     
        
        self.threadPool = ThreadPool()
        self.variables = config_json.get('preprocess_variables')
        
        if self.variables:
            self.variables = {
                x['id'] : Variable(x) for x in self.variables
            }
            self.variables_master_lock = Lock()
            self.variables_locks = {
                k: Lock() for k in self.variables
            }

    def run(self, turns: List[str], turn_idx: int) -> str:
        """

        Args:
            turns (str): concatentation of all past turns of the conversation
            turn_idx (int): turn number in the conversation used to set args of
            language model calls

        Returns:
            str: bot response given the generated/constant prompt using the default lm
        """
        
        self.turn_idx = turn_idx
        self.turns = turns 

        self._decode_tokens(self.instruction)
        messages = self._messages_compose()
            
        if turn_idx == 0:
            response =\
                self.endpoints[self.default_endpoint](
                    engine=self.engine,
                    messages=messages, 
                    n=10)
        else:
            response =\
                self.endpoints[self.default_endpoint](
                    engine=self.engine,
                    messages=messages, 
                    frequency_penalty=2, 
                    presence_penalty=2,
                    temperature=1
                )
                
        return response.strip()

    def _messages_compose(self): 
        """
        messages format for chatgpt endpoint (gpt-3.5-turbo). this can be easily parsed back to regular text for other plaintext endpoints
        """
        
        if self.few_shot_example == 'nvc':
            few_shot_example = self.get_fewshot_example(self.turn_idx)

            if few_shot_example != "":
                self.instruction = f'{self.instruction}\n{few_shot_example}\n'
        
        seed_turns = [x[0] for x in self.turns if x[-1]]
        non_seed_turns = [x[0] for x in self.turns if not x[-1]]
                
        messages = [
            {"role": "system", "content": str(self.instruction)}, 
            {"role": "user", "content": "\n".join(seed_turns).strip()}
        ]
        
        role = "assistant"
        for t in non_seed_turns: 
            messages.append({
                "role": role, 
                "content": t
            })
            
            role = "user" if role == "assistant" else "assistant"
        
        return messages
        
    def _decode_tokens(self, variable: str) -> Variable:
        def _get_endpoint(leaf_variable):
            return leaf_variable.get(
                'endpoint',
                self.default_endpoint
            )
        def _decode_token(token: str):
            token_split = re.findall(ROOT_TOKEN_REGEX, token)
            token_root = token_split[0]
            with self.variables_master_lock:
                variable_lock = self.variables_locks[token_root]
                
            with variable_lock:
                leaf_variable = self.variables.get(token_root)
                if not leaf_variable:
                    raise Exception(
                        f'{token_root} not defined in preprocess variables.'
                    )
                    
                if leaf_variable.is_assignable(self.turn_idx):  
                    # Need to be queried      

                    log.debug(
                        f'From {variable.get("id", "init")} '
                        f'Executig call #{leaf_variable._assign_cnt + 1} '
                        f'to obtain variable {leaf_variable["id"]}'
                    )
                    # print(
                    #     f'From {variable.get("id", "init")} '
                    #     f'Executig call #{leaf_variable._assign_cnt + 1} '
                    #     f'to obtain variable {leaf_variable["id"]}'
                    # )
                    
                    sub_instruction = str(self._decode_tokens(leaf_variable,))   
                    
                    messages = [
                        {"role": "system", "content": "\n".join([t[0] for t in self.turns] + [sub_instruction]).strip()}
                    ]
          
                    leaf_variable['response'] =\
                        self.endpoints[_get_endpoint(leaf_variable)](
                            engine=self.engine, 
                            messages=messages
                        )
                    
                    value = self.reduce(leaf_variable)
                    if value is None:
                        log.error(
                            'Multiple calls in the same turn might arise as'
                            'None reduction is observed'
                        )
                    leaf_variable.assign(
                        value,
                        turn_idx=self.turn_idx
                    )
            
            # Support other value formats such as 'value-list'
            token_format = '-'.join(token_split[1:])
            return leaf_variable, token_format
        
        tokens = variable.get_tokens()
        for token, decoding_var__format in zip(
            tokens, 
            self.threadPool.map(_decode_token, tokens
        )):
            variable.replace(token, decoding_var__format)

        return variable
    
    @staticmethod
    def get_fewshot_example(turn_idx):
        full_example = [
            "user A: The Most Arrogant Speaker We've Ever Had!\n"\
            "wisebeing: Are you reacting to my having taken thirty straight minutes to present my views before giving you a chance to talk?\n",
            "user A: No, you make it sound so simple.\n"\
            "wisebeing: Are you reacting to my not having said anything about how the process can be difficult for some people to apply?\n",
            "user A: No, not some people—you!\n"\
            "wisebeing: So you're reacting to my not having said that the process can be difficult for me at times?\n",
            "user A: That's right.\n"\
            "wisebeing: Are you feeling annoyed because you would have liked some sign from me that indicated that I have some problems with the process myself?\n",
            "user A: That's right.\n"\
            "wisebeing: Would you like me to admit right now that this process can be a struggle for me to apply?\n",
            "use A: Yes\n"\
            "wisebeing: Yes, this process is often difficult for me. As we continue with the workshop,"\
                "you'll probably hear me describe several incidents where I've struggled… or completely lost touch… "\
                "with this process, this consciousness, that I am presenting here to you. But what keeps me in the struggle "\
                "are the close connections to other people that happen when I do stay with the process."
        ]
        return "".join(full_example[:turn_idx+1])
    
    def reduce(self, leaf_variable):
        reduction = leaf_variable['response']
        if leaf_variable.get('post_regex'):
            reduction = re.findall(str(self._decode_tokens(
                    Variable(leaf_variable['post_regex'].lower()), 
                )),
                reduction.lower()
            )
            leaf_variable.assign(str(reduction), format='list')
        
        post_func = leaf_variable.get('post_func')
        if post_func:
            if not isinstance(post_func, list):
                post_func = [post_func]
            for func in post_func:
                reduction = eval(str(
                    self._decode_tokens(
                        Variable(func)
                    )
                ))(reduction)
        
        return reduction
    

    def is_dynamic_prompt(self): 
        return not self.instruction.is_constant()
    
    def backspace(self): 
        [v.backspace() for v in self.variables.values()]
            
    def debug_prompt(self): return self.instruction.trace()

    def debug_variables(self):
        out = ""
        for k, v in self.variables.items():
            out += f'###### Variable({k})\n'
            out += f'### assign_cnt: {v._assign_cnt}\n'
            out += f'### assignments:\n' 
            out += "\n".join(
                [f"- @{k}: {v}" for k, v in v._assignments.items()]
            ) + "\n"
            out += f'### tokens:\n'
            out += "\n".join(
                [f'- {k} = {v}' for k, v in v._variables.items()]
            ) + "\n"
            out += f'### instruction-out: {str(v)}\n'
            out += '### extra parameters:\n'
            out += "- \n".join(
                [f'- {k}: {v}' for k, v in v._parameters.items()]
            ) + "\n"
        return out
    