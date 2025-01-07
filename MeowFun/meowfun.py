from typing import Optional
import aiohttp
import random
from redbot.core import commands, app_commands
from redbot.core.bot import Red
from redbot.core.config import Config
import discord

class MeowFun(commands.Cog):
    """A collection of fun and unique commands for your Discord server!"""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=897234789234,
            force_registration=True,
        )
        self.session = aiohttp.ClientSession()
        
        # Define default global settings if needed
        default_global = {}
        
        # Define default guild settings if needed
        default_guild = {}
        
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

    async def cog_unload(self) -> None:
        """Cleanup method that will be called when the cog unloads."""
        if self.session:
            await self.session.close()

    @app_commands.command(name="randomgif", description="Get a completely random funny GIF!")
    @app_commands.describe(category="Optional category for the type of funny GIF you want")
    @app_commands.choices(category=[
        app_commands.Choice(name="Animals", value="funny animals"),
        app_commands.Choice(name="Fails", value="epic fail"),
        app_commands.Choice(name="Reactions", value="funny reaction"),
        app_commands.Choice(name="Pranks", value="funny prank"),
        app_commands.Choice(name="Cats", value="cat funny"),
        app_commands.Choice(name="Dogs", value="dog funny"),
        app_commands.Choice(name="IASIP", value="always sunny philadelphia"),
        app_commands.Choice(name="Random", value="random")
    ])
    async def randomgif(
        self, 
        interaction: discord.Interaction, 
        category: app_commands.Choice[str] = None
    ) -> None:
        """Get a completely random funny GIF!
        
        Parameters
        ----------
        category: Optional category for the type of funny GIF you want
        """
        await interaction.response.defer()

        # Category-specific search terms
        search_terms = {
            "funny animals": [
                "funny animals", "animal fails", "cute animal funny",
                "pets funny", "animals being derps", "funny zoo animals",
                "wildlife funny", "farm animals funny"
            ],
            "epic fail": [
                "epic fail", "fail compilation", "funny fail",
                "epic fails funny", "fail moments", "best fails",
                "spectacular fails", "embarrassing fails"
            ],
            "funny reaction": [
                "funny reaction", "reaction gif", "funny face reaction",
                "shocked reaction", "surprised reaction", "wtf reaction",
                "laugh reaction", "facepalm reaction"
            ],
            "funny prank": [
                "funny prank", "harmless pranks", "prank compilation",
                "funny practical jokes", "best pranks", "prank fails",
                "funny tricks", "silly pranks"
            ],
            "cat funny": [
                "cat funny", "funny cats", "cat fails", "kitten funny",
                "cats being weird", "cat pranks", "cat vs cucumber",
                "cats knocking things", "cat zoomies"
            ],
            "dog funny": [
                "dog funny", "funny dogs", "puppy funny", "dog fails",
                "dogs being derps", "dog zoomies", "silly dogs",
                "dog vs mirror", "dogs playing"
            ],
            "always sunny philadelphia": [
                "always sunny in philadelphia", "charlie day", 
                "danny devito always sunny", "dennis reynolds",
                "mac always sunny", "frank reynolds",
                "dee reynolds", "the gang", "paddy's pub",
                "charlie kelly", "dennis system", "nightman",
                "dayman fighter of the nightman", "rum ham",
                "wild card charlie", "pepe silvia"
            ],
            "random": [
                "funny", "hilarious", "fail", "laugh", "comedy",
                "meme", "humor", "funny moments", "funny clips",
                "comedy gold", "funny accidents", "funny bloopers",
                "funny compilation", "best funny moments"
            ]
        }
        
        # Select search term based on category
        if category and category.value in search_terms:
            search_term = random.choice(search_terms[category.value])
        else:
            # If random or invalid category, pick from all terms
            all_terms = [term for terms in search_terms.values() for term in terms]
            search_term = random.choice(all_terms)
        
        # Add some randomness to the API call
        limit = random.randint(5, 20)  # Get multiple results and pick one randomly
        
        try:
            # Using tenor's API with more random parameters
            async with self.session.get(
                f"https://g.tenor.com/v1/random?q={search_term}&key=LIVDSRZULELA&limit={limit}"
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("results"):
                        # Randomly select one GIF from the results
                        gif_result = random.choice(data["results"])
                        gif_url = gif_result["media"][0]["gif"]["url"]
                        
                        # Create a more visually appealing embed
                        category_emojis = {
                            "funny animals": "🐾",
                            "epic fail": "💥",
                            "funny reaction": "😆",
                            "funny prank": "🎭",
                            "cat funny": "🐱",
                            "dog funny": "🐶",
                            "always sunny philadelphia": "🌞",
                            "random": "🎲"
                        }
                        
                        emoji = category_emojis.get(category.value if category else "random", "🎭")
                        
                        embed = discord.Embed(
                            title=f"{emoji} Random Funny GIF {emoji}",
                            description=f"Here's your {category.name.lower() if category and category.value != 'random' else 'random'} GIF!",
                            color=discord.Color.random()
                        )
                        embed.set_image(url=gif_url)
                        
                        # Add search info in footer
                        if category and category.value != "random":
                            embed.set_footer(text=f"Category: {category.name} | Powered by Tenor")
                        else:
                            embed.set_footer(text="Random Category | Powered by Tenor")
                        
                        await interaction.followup.send(embed=embed)
                    else:
                        await interaction.followup.send("Couldn't find any GIFs! Try a different category 😅")
                else:
                    await interaction.followup.send("Oops! Something went wrong while fetching the GIF! Try again later 😿")
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {str(e)}") 