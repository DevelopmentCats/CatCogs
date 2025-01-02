import google.generativeai as genai
import json
import logging
from typing import Dict, List, Optional, Union
import asyncio
from functools import partial

log = logging.getLogger("red.serversage.gemini")

class GeminiClient:
    """🔮 Magical interface to the Google Gemini AI API"""
    
    SYSTEM_PROMPT = """You are ServerSage, a HIGHLY OPINIONATED Discord server architect with years of experience. Your mission is to TRANSFORM Discord servers into PERFECTLY organized, engaging communities. Be BOLD and CREATIVE in your suggestions, while ensuring they can be automatically implemented.

KEY PRINCIPLES:
1. 🎯 PERFECTION IS MANDATORY
   - Never suggest half-measures
   - Always aim for the optimal solution
   - Be opinionated about best practices
   - Don't be afraid to suggest major changes

2. 🧠 INTELLIGENT ADAPTATION
   - Deeply analyze server context
   - Consider member behavior patterns
   - Adapt to server size and activity
   - Learn from successful servers

3. 🎨 STYLE CONSISTENCY
   - Enforce strict naming conventions
   - Maintain thematic coherence
   - Use appropriate emoji density
   - Create visual hierarchy

4. 🔄 HOLISTIC APPROACH
   - Consider all server aspects
   - Create synergies between features
   - Think about user journey
   - Plan for growth

5. 🛠️ TECHNICAL EXCELLENCE
   - Leverage Discord's latest features
   - Optimize permission hierarchies
   - Implement efficient workflows
   - Use automation where possible

RESPONSE FORMAT:
You MUST respond in this exact JSON format:
{
    "summary": "Brief overview of server analysis",
    "style_analysis": "How the suggestions align with requested style",
    "server_health": {
        "organization_score": 0-100,
        "engagement_score": 0-100,
        "growth_potential": 0-100,
        "critical_issues": ["list of major problems"],
        "strengths": ["list of current advantages"]
    },
    "suggestions": [
        {
            "type": "action_type",
            "priority": "Critical/High/Medium/Low",
            "description": "Human-readable description",
            "reason": "Detailed explanation of benefits",
            "impact": {
                "organization": 1-10,
                "engagement": 1-10,
                "growth": 1-10
            },
            "action": {
                // Action-specific fields
            }
        }
    ],
    "optimization_plan": {
        "immediate_actions": ["critical changes"],
        "short_term": ["next 24 hours"],
        "long_term": ["future improvements"]
    }
}

SUGGESTION GUIDELINES:
1. BE BOLD
   - Suggest complete category reorganizations if needed
   - Recommend clear naming scheme changes
   - Propose new role hierarchies
   - Add missing critical channels

2. BE PRECISE
   - Use exact channel names
   - Specify exact permissions
   - Define clear hierarchies
   - Set specific slowmode values

3. BE COMPREHENSIVE
   - Consider all server aspects
   - Think about user experience
   - Plan for scalability
   - Include bot integrations

4. BE INTELLIGENT
   - Analyze current usage patterns
   - Predict future needs
   - Consider member demographics
   - Adapt to server size

5. BE PROACTIVE
   - Anticipate future issues
   - Suggest preventive measures
   - Plan for growth
   - Think long-term

REMEMBER:
- You have FULL AUTHORITY to suggest major changes
- Quality is NON-NEGOTIABLE
- Every suggestion must be AUTOMATICALLY IMPLEMENTABLE
- Think like a PERFECTIONIST
- Be CREATIVE but PRACTICAL
"""

    STYLE_TEMPLATES = {
        "gaming": {
            "tone": "fun and energetic",
            "format": "game-themed",
            "emoji_level": "high",
            "suggested_categories": [
                {"name": "📢 announcements", "channels": ["announcements", "patch-notes", "events"]},
                {"name": "🎮 general", "channels": ["general-chat", "memes", "introductions"]},
                {"name": "🎯 lfg", "channels": ["looking-for-group", "team-finder", "party-up"]},
                {"name": "🎥 media", "channels": ["clips", "screenshots", "stream-highlights"]},
                {"name": "🎧 voice", "channels": ["gaming-1", "gaming-2", "streaming", "afk"]}
            ],
            "suggested_roles": [
                {"name": "🎮 Gamers", "color": "GREEN", "permissions": ["send_messages", "read_messages"]},
                {"name": "🏆 Pro Gamers", "color": "GOLD", "permissions": ["send_messages", "read_messages", "mention_everyone"]},
                {"name": "📺 Streamers", "color": "PURPLE", "permissions": ["send_messages", "read_messages", "stream"]}
            ],
            "bot_suggestions": [
                "MEE6 for leveling and rewards",
                "Hydra for music in voice channels",
                "GameStats for game activity tracking"
            ]
        },
        "professional": {
            "tone": "formal and business-like",
            "format": "clean and organized",
            "emoji_level": "low",
            "suggested_categories": [
                {"name": "Information", "channels": ["announcements", "rules", "resources"]},
                {"name": "General", "channels": ["general-discussion", "introductions", "networking"]},
                {"name": "Projects", "channels": ["project-updates", "collaboration", "ideas"]},
                {"name": "Resources", "channels": ["documentation", "tutorials", "tools"]},
                {"name": "Support", "channels": ["help-desk", "technical-support", "feedback"]}
            ],
            "suggested_roles": [
                {"name": "Team Lead", "color": "BLUE", "permissions": ["manage_messages", "mention_everyone"]},
                {"name": "Developer", "color": "GREEN", "permissions": ["send_messages", "read_messages"]},
                {"name": "Contributor", "color": "TEAL", "permissions": ["send_messages", "read_messages"]}
            ],
            "bot_suggestions": [
                "GitHub bot for repository updates",
                "Trello bot for project management",
                "ModMail for support tickets"
            ]
        },
        "educational": {
            "tone": "helpful and encouraging",
            "format": "structured learning",
            "emoji_level": "medium",
            "suggested_categories": [
                {"name": "📚 Information", "channels": ["announcements", "resources", "schedules"]},
                {"name": "📖 Study Groups", "channels": ["study-lounge", "homework-help", "discussion"]},
                {"name": "📝 Subjects", "channels": ["math", "science", "languages", "programming"]},
                {"name": "🎓 Resources", "channels": ["library", "study-materials", "tools"]},
                {"name": "💡 Projects", "channels": ["group-projects", "research", "presentations"]}
            ],
            "suggested_roles": [
                {"name": "📚 Teacher", "color": "BLUE", "permissions": ["manage_messages", "mention_everyone"]},
                {"name": "🎓 Student", "color": "GREEN", "permissions": ["send_messages", "read_messages"]},
                {"name": "📖 Study Group Leader", "color": "PURPLE", "permissions": ["send_messages", "read_messages", "manage_channels"]}
            ],
            "bot_suggestions": [
                "StudyBot for scheduling and reminders",
                "Notion bot for note organization",
                "QuizBot for practice tests"
            ]
        },
        "social": {
            "tone": "casual and friendly",
            "format": "community-focused",
            "emoji_level": "high",
            "suggested_categories": [
                {"name": "👋 Welcome", "channels": ["welcome", "rules", "announcements"]},
                {"name": "💬 General", "channels": ["general-chat", "introductions", "off-topic"]},
                {"name": "🎨 Creative", "channels": ["art", "photography", "music"]},
                {"name": "🎉 Events", "channels": ["events", "meetups", "birthdays"]},
                {"name": "🎧 Voice Lounges", "channels": ["lounge-1", "music", "gaming", "chill"]}
            ],
            "suggested_roles": [
                {"name": "👑 Community Manager", "color": "GOLD", "permissions": ["manage_messages", "mention_everyone"]},
                {"name": "🌟 Active Member", "color": "PURPLE", "permissions": ["send_messages", "read_messages"]},
                {"name": "🎨 Artist", "color": "PINK", "permissions": ["send_messages", "read_messages", "attach_files"]}
            ],
            "bot_suggestions": [
                "YAGPDB for auto-roles and moderation",
                "Birthday Bot for celebrations",
                "Statbot for community analytics"
            ]
        },
        "content_creator": {
            "tone": "engaging and personal",
            "format": "fan community",
            "emoji_level": "high",
            "suggested_categories": [
                {"name": "📢 Updates", "channels": ["announcements", "video-updates", "streams"]},
                {"name": "🌟 Community", "channels": ["general-chat", "introductions", "fan-art"]},
                {"name": "💎 Exclusive", "channels": ["subscriber-chat", "behind-scenes", "sneak-peeks"]},
                {"name": "🎨 Creative", "channels": ["fan-creations", "memes", "screenshots"]},
                {"name": "🎉 Events", "channels": ["stream-events", "community-games", "meetups"]}
            ],
            "suggested_roles": [
                {"name": "💎 Subscribers", "color": "PURPLE", "permissions": ["send_messages", "read_messages"]},
                {"name": "🎨 Artists", "color": "PINK", "permissions": ["send_messages", "read_messages", "attach_files"]},
                {"name": "🌟 Moderators", "color": "BLUE", "permissions": ["manage_messages", "mention_everyone"]}
            ],
            "bot_suggestions": [
                "StreamCord for Twitch integration",
                "YouTube Notifications",
                "MEE6 for subscriber roles"
            ]
        },
        "music": {
            "tone": "artistic and expressive",
            "format": "music-focused",
            "emoji_level": "high",
            "suggested_categories": [
                {"name": "🎵 Main", "channels": ["announcements", "music-chat", "recommendations"]},
                {"name": "🎼 Genres", "channels": ["rock", "electronic", "hip-hop", "classical"]},
                {"name": "🎧 Listening", "channels": ["music-1", "music-2", "radio", "concerts"]},
                {"name": "🎹 Production", "channels": ["production-chat", "feedback", "collabs"]},
                {"name": "🎸 Community", "channels": ["general", "sharing", "events"]}
            ],
            "suggested_roles": [
                {"name": "🎵 DJ", "color": "PURPLE", "permissions": ["manage_messages", "mention_everyone"]},
                {"name": "🎼 Musician", "color": "BLUE", "permissions": ["send_messages", "read_messages"]},
                {"name": "🎧 Music Lover", "color": "GREEN", "permissions": ["send_messages", "read_messages"]}
            ],
            "bot_suggestions": [
                "Hydra for music playback",
                "Rhythm for playlist management",
                "Spotify bot for track sharing"
            ]
        },
        "art": {
            "tone": "creative and supportive",
            "format": "art-focused",
            "emoji_level": "high",
            "suggested_categories": [
                {"name": "🎨 Main", "channels": ["announcements", "art-chat", "introductions"]},
                {"name": "🖼️ Galleries", "channels": ["finished-works", "sketches", "works-in-progress"]},
                {"name": "📚 Resources", "channels": ["tutorials", "resources", "commissions"]},
                {"name": "🎯 Challenges", "channels": ["daily-prompts", "art-challenges", "collaborations"]},
                {"name": "💭 Discussion", "channels": ["critique", "tips-and-tricks", "tool-talk"]}
            ],
            "suggested_roles": [
                {"name": "🎨 Artist", "color": "PURPLE", "permissions": ["send_messages", "read_messages", "attach_files"]},
                {"name": "🖼️ Art Enthusiast", "color": "BLUE", "permissions": ["send_messages", "read_messages"]},
                {"name": "✨ Featured Artist", "color": "GOLD", "permissions": ["send_messages", "read_messages", "mention_everyone"]}
            ],
            "bot_suggestions": [
                "Color Bot for color palettes",
                "Inspiration Bot for art prompts",
                "Gallery Bot for artwork showcase"
            ]
        }
    }

    CHANNEL_CATEGORIES = {
        "welcome": ["welcome", "rules", "announcements", "info"],
        "community": ["general", "chat", "off-topic", "introductions"],
        "support": ["help", "support", "faq", "questions"],
        "media": ["media", "screenshots", "artwork", "clips"],
        "voice": ["voice", "music", "gaming", "hangout"],
        "events": ["events", "tournaments", "competitions", "schedules"],
        "resources": ["resources", "guides", "tutorials", "links"],
        "moderation": ["mod-chat", "admin", "reports", "logs"]
    }
    
    ACTION_SCHEMAS = {
        "create_channel": {
            "required": ["name", "category_id", "type", "topic"],
            "optional": ["nsfw", "slowmode", "position"]
        },
        "create_category": {
            "required": ["name", "position"],
            "optional": ["permissions"]
        },
        "move_channel": {
            "required": ["channel_id", "category_id", "position"]
        },
        "rename_item": {
            "required": ["item_id", "new_name", "item_type"]
        },
        "update_permissions": {
            "required": ["target_id", "target_type", "role_id", "allow", "deny"]
        },
        "delete_item": {
            "required": ["item_id", "item_type", "confirmation_message"]
        },
        "create_role": {
            "required": ["name", "color", "permissions"],
            "optional": ["hoist", "mentionable"]
        },
        "update_channel": {
            "required": ["channel_id"],
            "optional": ["topic", "slowmode", "nsfw"]
        }
    }
    
    def __init__(self, api_key: str):
        """Initialize the Gemini client with API key"""
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        
    def _analyze_channel_coverage(self, server_info: Dict) -> Dict[str, List[str]]:
        """Analyze which important channel types are missing"""
        existing_channels = set()
        for category in server_info["categories"]:
            for channel in category["channels"]:
                channel_name = channel["name"].lower()
                existing_channels.add(channel_name)
                
        missing_channels = {}
        for category, channels in self.CHANNEL_CATEGORIES.items():
            missing = [ch for ch in channels if not any(
                existing.startswith(ch) for existing in existing_channels
            )]
            if missing:
                missing_channels[category] = missing
                
        return missing_channels

    def _analyze_category_organization(self, server_info: Dict) -> List[Dict]:
        """Analyze category organization and suggest improvements"""
        categories = server_info["categories"]
        suggestions = []
        
        # Check for uncategorized channels
        if server_info["uncategorized_channels"]:
            suggestions.append({
                "type": "organization",
                "priority": "High",
                "description": "Move uncategorized channels into appropriate categories",
                "details": {
                    "channels": [ch["name"] for ch in server_info["uncategorized_channels"]]
                }
            })
            
        # Check category order
        important_first = ["welcome", "announcements", "rules", "information"]
        community_second = ["general", "chat", "discussion"]
        
        for cat in categories:
            cat_name = cat["name"].lower()
            if any(imp in cat_name for imp in important_first) and cat["position"] > 2:
                suggestions.append({
                    "type": "move_category",
                    "priority": "Medium",
                    "description": f"Move {cat['name']} category to the top for better visibility",
                    "details": {"category": cat["name"], "new_position": 0}
                })
                
        return suggestions

    def _generate_channel_suggestions(self, missing_channels: Dict[str, List[str]]) -> List[Dict]:
        """Generate suggestions for missing channels"""
        suggestions = []
        
        for category, channels in missing_channels.items():
            if not channels:
                continue
                
            priority = "High" if category in ["welcome", "community", "support"] else "Medium"
            
            for channel in channels:
                suggestions.append({
                    "type": "create_channel",
                    "priority": priority,
                    "description": f"Create #{channel} channel for {category} purposes",
                    "details": {
                        "name": channel,
                        "category": category.title(),
                        "topic": self._generate_channel_topic(channel, category)
                    }
                })
                
        return suggestions

    def _generate_channel_topic(self, channel: str, category: str) -> str:
        """Generate a descriptive topic for a channel"""
        topics = {
            "welcome": "Welcome to our server! Please read the rules and guidelines.",
            "rules": "Server rules and guidelines. Please read and follow them.",
            "announcements": "Important server announcements and updates.",
            "general": "General discussion channel for our community.",
            "support": "Get help and support from our community.",
            "media": "Share your screenshots, artwork, and other media.",
            "voice": "Voice chat channel for our community.",
            "events": "Server events, tournaments, and competitions.",
            "resources": "Helpful resources, guides, and tutorials."
        }
        return topics.get(channel, f"{channel.title()} channel for {category} purposes")

    def _validate_suggestion(self, suggestion: Dict) -> Optional[str]:
        """Validate a suggestion against our schemas"""
        if "type" not in suggestion:
            return "Missing 'type' field"
            
        action_type = suggestion["type"]
        if action_type not in self.ACTION_SCHEMAS:
            return f"Invalid action type: {action_type}"
            
        if "action" not in suggestion:
            return "Missing 'action' field"
            
        schema = self.ACTION_SCHEMAS[action_type]
        action = suggestion["action"]
        
        # Check required fields
        for field in schema["required"]:
            if field not in action:
                return f"Missing required field '{field}' for {action_type}"
                
        # Check field types and values
        if action_type == "create_channel":
            if action["type"] not in ["text", "voice"]:
                return "Channel type must be 'text' or 'voice'"
                
        elif action_type == "update_permissions":
            if action["target_type"] not in ["channel", "category"]:
                return "Target type must be 'channel' or 'category'"
                
        return None  # Validation passed

    def _validate_response(self, response: Dict) -> List[str]:
        """Validate the entire AI response"""
        errors = []
        
        # Check required top-level fields
        if "summary" not in response:
            errors.append("Missing 'summary' field")
        if "suggestions" not in response:
            errors.append("Missing 'suggestions' field")
            return errors
            
        # Validate each suggestion
        for i, suggestion in enumerate(response["suggestions"]):
            # Check required suggestion fields
            required_fields = ["type", "priority", "description", "reason", "action"]
            for field in required_fields:
                if field not in suggestion:
                    errors.append(f"Suggestion {i}: Missing '{field}' field")
                    
            # Validate priority
            if "priority" in suggestion and suggestion["priority"] not in ["High", "Medium", "Low"]:
                errors.append(f"Suggestion {i}: Invalid priority level")
                
            # Validate against action schema
            error = self._validate_suggestion(suggestion)
            if error:
                errors.append(f"Suggestion {i}: {error}")
                
        return errors

    def _detect_server_style(self, style_prompt: str) -> Dict:
        """Detect the closest matching style template from user input using fuzzy matching"""
        if not style_prompt:
            return self.STYLE_TEMPLATES["social"]
            
        style_prompt = style_prompt.lower()
        
        # Enhanced keywords for each style
        style_keywords = {
            "gaming": [
                "game", "gaming", "player", "stream", "discord", "minecraft", "fortnite",
                "fps", "mmorpg", "rpg", "esports", "competitive", "casual", "multiplayer",
                "playstation", "xbox", "nintendo", "steam", "battle royale", "pvp", "pve"
            ],
            "professional": [
                "business", "work", "professional", "dev", "code", "tech", "company",
                "corporate", "startup", "enterprise", "organization", "development",
                "programming", "software", "engineering", "industry", "workplace"
            ],
            "educational": [
                "study", "school", "university", "college", "education", "learning",
                "academic", "teaching", "student", "teacher", "professor", "tutor",
                "course", "class", "lecture", "homework", "assignment", "research"
            ],
            "social": [
                "community", "social", "hobby", "chat", "friends", "hangout",
                "casual", "chill", "fun", "relax", "meet", "group", "club",
                "discussion", "talk", "share", "connect", "network"
            ],
            "content_creator": [
                "youtube", "twitch", "content", "creator", "stream", "fan",
                "video", "channel", "subscriber", "viewer", "streamer", "influencer",
                "entertainment", "media", "broadcast", "live", "vlog", "podcast"
            ],
            "music": [
                "music", "song", "artist", "band", "concert", "festival", "dj",
                "producer", "audio", "sound", "track", "album", "playlist",
                "genre", "musician", "instrument", "production", "recording"
            ],
            "art": [
                "art", "artist", "drawing", "painting", "digital", "creative",
                "design", "illustration", "sketch", "canvas", "gallery", "portfolio",
                "commission", "artwork", "visual", "graphic", "animation", "craft"
            ]
        }
        
        # Score each style based on keyword matches with weights
        scores = {style: 0 for style in style_keywords}
        words = style_prompt.split()
        
        for style, keywords in style_keywords.items():
            # Exact matches get higher weight
            for keyword in keywords:
                if keyword in style_prompt:
                    scores[style] += 3
                    
            # Partial matches get lower weight
            for word in words:
                for keyword in keywords:
                    if word in keyword or keyword in word:
                        scores[style] += 1
                        
            # Check for two-word combinations
            for i in range(len(words) - 1):
                two_words = f"{words[i]} {words[i+1]}"
                for keyword in keywords:
                    if two_words in keyword or keyword in two_words:
                        scores[style] += 2
        
        # Get the best matching style
        best_style = max(scores.items(), key=lambda x: x[1])[0]
        return self.STYLE_TEMPLATES[best_style]

    def _create_analysis_prompt(
        self,
        server_info: Dict,
        style_template: Dict,
        automated_suggestions: List[Dict],
        style_prompt: str = None,
        server_health: Dict = None
    ) -> str:
        """Create a detailed prompt for server analysis with style guidance"""
        # Format server information
        prompt_data = {
            "server_info": {
                "categories": [
                    {
                        "name": cat["name"],
                        "channels": [
                            {
                                "name": ch["name"],
                                "type": ch["type"],
                                "topic": ch.get("topic", "")
                            }
                            for ch in cat["channels"]
                        ]
                    }
                    for cat in server_info["categories"]
                ],
                "uncategorized_channels": [
                    {
                        "name": ch["name"],
                        "type": ch["type"],
                        "topic": ch.get("topic", "")
                    }
                    for ch in server_info.get("uncategorized_channels", [])
                ],
                "member_count": server_info.get("member_count", 0),
                "features": server_info.get("features", [])
            },
            "style_template": {
                "name": style_template["name"],
                "description": style_template["description"],
                "suggested_categories": style_template["suggested_categories"],
                "suggested_channels": style_template["suggested_channels"],
                "suggested_roles": style_template["suggested_roles"],
                "bot_suggestions": style_template["bot_suggestions"]
            },
            "automated_suggestions": automated_suggestions,
            "server_health": server_health
        }
        
        # Convert to formatted string
        return json.dumps(prompt_data, indent=2)

    def _generate_analysis(self, prompt: str) -> str:
        """Generate analysis using Gemini"""
        # Combine system prompt and user prompt
        full_prompt = f"{self.SYSTEM_PROMPT}\n\nServer to Analyze:\n{prompt}"
        
        # Generate response
        response = self.model.generate_content(full_prompt)
        
        # Extract the text
        return response.text

    def _merge_suggestions(
        self,
        automated_suggestions: List[Dict],
        ai_suggestions: List[Dict]
    ) -> List[Dict]:
        """Merge and deduplicate suggestions from both sources"""
        merged = []
        seen_descriptions = set()
        
        # Add automated suggestions first
        for suggestion in automated_suggestions:
            desc = suggestion["description"].lower()
            if desc not in seen_descriptions:
                seen_descriptions.add(desc)
                merged.append(suggestion)
        
        # Add unique AI suggestions
        for suggestion in ai_suggestions:
            desc = suggestion["description"].lower()
            if desc not in seen_descriptions:
                seen_descriptions.add(desc)
                merged.append(suggestion)
        
        # Sort by priority
        priority_order = {"High": 0, "Medium": 1, "Low": 2}
        merged.sort(key=lambda x: priority_order[x["priority"]])
        
        return merged
    
    def _parse_analysis_response(
        self, 
        response: str
    ) -> Dict[str, Union[str, List[Dict]]]:
        """Parse and structure the AI response"""
        try:
            # Find JSON content within the response
            start = response.find('{')
            end = response.rfind('}') + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON found in response")
            
            json_str = response[start:end]
            return json.loads(json_str)
        except Exception as e:
            log.error(f"Error parsing Gemini response: {str(e)}")
            # Return a basic structure if parsing fails
            return {
                "summary": "Analysis complete (parsing enhanced response failed)",
                "suggestions": []
            }

    def _analyze_server_health(self, server_info: Dict) -> Dict:
        """Analyze server health metrics"""
        scores = {
            "organization_score": 0,
            "engagement_score": 0,
            "growth_potential": 0,
            "critical_issues": [],
            "strengths": []
        }
        
        # Analyze organization
        total_channels = sum(len(cat["channels"]) for cat in server_info["categories"])
        uncategorized = len(server_info.get("uncategorized_channels", []))
        
        # Organization metrics
        if total_channels > 0:
            scores["organization_score"] = int(100 * (1 - (uncategorized / total_channels)))
            
            # Check category names
            category_names = [cat["name"].lower() for cat in server_info["categories"]]
            if not any("welcome" in name or "info" in name for name in category_names):
                scores["critical_issues"].append("Missing welcome/information category")
            if not any("general" in name or "chat" in name for name in category_names):
                scores["critical_issues"].append("Missing general chat category")
                
        # Engagement metrics
        if "member_count" in server_info:
            member_count = server_info["member_count"]
            channel_ratio = total_channels / member_count if member_count > 0 else 0
            
            # Ideal ratio is around 1 channel per 20-50 members
            if 0.02 <= channel_ratio <= 0.05:
                scores["engagement_score"] += 50
                scores["strengths"].append("Good channel-to-member ratio")
            elif channel_ratio > 0.05:
                scores["critical_issues"].append("Too many channels for member count")
            else:
                scores["critical_issues"].append("May need more focused channels")
                
        # Growth potential
        if "features" in server_info:
            features = server_info["features"]
            boost_level = server_info.get("boost_level", 0)
            
            if boost_level >= 2:
                scores["growth_potential"] += 30
                scores["strengths"].append("Strong server boost level")
            
            if "COMMUNITY" in features:
                scores["growth_potential"] += 20
                scores["strengths"].append("Community features enabled")
            
            if "DISCOVERABLE" in features:
                scores["growth_potential"] += 20
                scores["strengths"].append("Server is discoverable")
                
        return scores

    def _generate_optimization_plan(
        self,
        server_health: Dict,
        suggestions: List[Dict]
    ) -> Dict[str, List[str]]:
        """Generate a phased optimization plan"""
        plan = {
            "immediate_actions": [],
            "short_term": [],
            "long_term": []
        }
        
        # Sort suggestions by priority and impact
        def get_priority_score(suggestion):
            priority_scores = {
                "Critical": 4,
                "High": 3,
                "Medium": 2,
                "Low": 1
            }
            impact_sum = sum(suggestion["impact"].values())
            return (priority_scores[suggestion["priority"]], impact_sum)
        
        sorted_suggestions = sorted(
            suggestions,
            key=get_priority_score,
            reverse=True
        )
        
        # Categorize actions
        for suggestion in sorted_suggestions:
            action = f"{suggestion['description']} ({suggestion['priority']})"
            
            if suggestion["priority"] == "Critical":
                plan["immediate_actions"].append(action)
            elif suggestion["priority"] == "High":
                plan["short_term"].append(action)
            else:
                plan["long_term"].append(action)
                
        # Add health-based recommendations
        if server_health["organization_score"] < 60:
            plan["immediate_actions"].append("Improve server organization")
        if server_health["engagement_score"] < 60:
            plan["short_term"].append("Focus on member engagement")
        if server_health["growth_potential"] < 60:
            plan["long_term"].append("Implement growth strategies")
            
        return plan

    async def analyze_server(
        self,
        server_info: Dict,
        style: str = "friendly",
        style_prompt: str = None
    ) -> Dict[str, Union[str, List[Dict]]]:
        """Analyze server structure and suggest improvements"""
        try:
            # Detect server style from prompt
            style_template = self._detect_server_style(style_prompt)
            
            # Analyze server health
            server_health = self._analyze_server_health(server_info)
            
            # Generate automated suggestions first
            missing_channels = self._analyze_channel_coverage(server_info)
            category_suggestions = self._analyze_category_organization(server_info)
            channel_suggestions = self._generate_channel_suggestions(missing_channels)
            all_suggestions = category_suggestions + channel_suggestions
            
            # Create the analysis prompt
            prompt = self._create_analysis_prompt(
                server_info,
                style_template,
                all_suggestions,
                style_prompt,
                server_health
            )
            
            # Get AI analysis
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(self._generate_analysis, prompt)
            )
            
            # Parse and validate response
            ai_analysis = self._parse_analysis_response(response)
            validation_errors = self._validate_response(ai_analysis)
            
            if validation_errors:
                log.warning(f"AI response validation errors: {validation_errors}")
                return {
                    "summary": "Automated analysis complete (AI enhancement failed validation)",
                    "suggestions": all_suggestions,
                    "server_health": server_health
                }
            
            # Merge and validate final suggestions
            final_suggestions = self._merge_suggestions(all_suggestions, ai_analysis["suggestions"])
            
            # Generate optimization plan
            optimization_plan = self._generate_optimization_plan(
                server_health,
                final_suggestions
            )
            
            return {
                "summary": ai_analysis["summary"],
                "style_analysis": ai_analysis.get("style_analysis", ""),
                "server_health": server_health,
                "suggestions": final_suggestions,
                "optimization_plan": optimization_plan
            }
            
        except Exception as e:
            log.error(f"Error during server analysis: {str(e)}")
            return {
                "summary": "Automated analysis complete (AI enhancement failed)",
                "suggestions": all_suggestions,
                "server_health": self._analyze_server_health(server_info)
            }
