from __future__ import annotations
from fastmcp import FastMCP
#from server.core import processing

####################################################################################################################
#                                                                                                                  #
#                                             PROMPTS PARA A GERAÇÃO ARQUITETURAL                                  #
#                                                                                                                  #
# -> Zero-shot                                                                                                     #
# -> Few-shot                                                                                                      #
# -> Chain-of-through                                                                                              #
####################################################################################################################


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="zero_shot_prompt",
        title="Zero Shot Prompting Style",
        description="Gera um prompt de geração arquitetural utilizando o modelo zero-short"
    )
    def zero_shot(
        textual_descriptions: str
    ) -> str:
        
        prompt = """

        """

        return prompt
    
    @mcp.prompt(
        name="Few_Shot_prompt",
        title="Few Shot Prompting Style",
        description="Gera um prompt de geração arquitetural utilizando o modelo few-shot"
    )
    def few_shot(
        textual_descriptions: str
    ) -> str:
        prompt = """

        """

        return prompt
