"""
Rugcheck filter implementation for token verification.
"""

import logging
from typing import List, Dict, Any
from config.settings import Settings
from config.rugcheck_api import RugcheckAPI
from utils.logger import get_logger

class RugcheckFilter:
    """Filter for checking token rugpull risk using Rugcheck API."""
    
    def __init__(self, rugcheck_api: RugcheckAPI, settings: Settings):
        """
        Initialize the Rugcheck filter.
        
        Args:
            rugcheck_api: Rugcheck API client instance
            settings: Application settings
        """
        self.rugcheck_api = rugcheck_api
        self.settings = settings
        self.logger = get_logger(__name__)
        
        # Get threshold values from settings
        self.max_rugcheck_score = settings.MAX_RUGCHECK_SCORE
        self.logger.info(f"RugcheckFilter initialized with maximum score threshold: {self.max_rugcheck_score}")
        
    async def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a token using Rugcheck API and return risk analysis.
        
        Args:
            token_data: Dictionary containing token info.
            
        Returns:
            Dict with analysis results including 'rugcheck_passed' status
        """
        token_address = token_data.get('mint')
        
        if not token_address:
            self.logger.warning(f"No mint address found for token (data: {token_data})")
            return {"rugcheck_passed": False, "reason": "missing_mint_address"}
            
        try:
            # Get rugcheck score data
            score_data = await self.rugcheck_api.get_token_score(token_address)
            self.logger.debug(f"Rugcheck API response for {token_address}: {str(score_data)[:500]}...")
            
            # Initialize base result structure, always including the raw data
            result = {
                "rugcheck_passed": False, # Default to False
                "reason": "unknown",
                "rugcheck_score": None,
                "rugcheck_data": score_data # Store the raw API response
            }

            # Check if the API call failed (returned None or specific error structure)
            # Handle cases where score_data might be None or an error dict like {"api_error": True}
            if score_data is None or score_data.get("api_error"):
                self.logger.warning(f"Rugcheck analysis failed for {token_address}. API returned no data or error.")
                result["reason"] = "api_error_or_not_found"
                result["rugcheck_score"] = -1 # Indicate failure
                return result # Return immediately with rugcheck_data containing None or error dict

            # --- Start processing the valid score_data ---
            # Extract normalized score (higher = more risk)
            score = score_data.get('score_normalised', 100) # Use normalized score, default to 100 if missing

            # Validate the score (ensure it's a number, handle infinity)
            try:
                score = float(score) # Convert potential string/int score to float
                if score == float('inf'): # Handle potential infinity from API?
                    self.logger.warning(f"Received infinite score_normalised for {token_address}, setting to 100.")
                    score = 100
            except (ValueError, TypeError):
                original_value = score_data.get('score_normalised') # Get original value for logging
                self.logger.warning(f"Invalid score_normalised format '{original_value}' for {token_address}, defaulting to 100.")
                score = 100

            # Update the score in the result dict
            result["rugcheck_score"] = score
            result["threshold"] = self.max_rugcheck_score # Add threshold for context
                
            # Check if score exceeds maximum acceptable score (lower is better)
            if score > self.max_rugcheck_score:
                self.logger.debug(f"Rugcheck FAIL for {token_address}: Score {score} > Threshold {self.max_rugcheck_score}")
                self.logger.info(f"Token {token_address} failed Rugcheck score: {score} > {self.max_rugcheck_score}")
                result["reason"] = "score_too_high"
                # rugcheck_passed remains False
                return result
                
            # Check for critical issues if available in the data
            critical_issues = score_data.get('critical_issues', [])
            if critical_issues:
                self.logger.info(f"Token {token_address} has critical issues: {critical_issues}")
                result["reason"] = "critical_issues"
                result["issues"] = critical_issues # Add issues details
                # rugcheck_passed remains False
                return result
                
            # If we get here, token passes rugcheck criteria
            self.logger.debug(f"Rugcheck PASS for {token_address}: Score {score} <= Threshold {self.max_rugcheck_score}")
            self.logger.info(f"Token {token_address} passed Rugcheck analysis with score {score}")
            result["rugcheck_passed"] = True
            result["reason"] = "passed"
            # Add critical issues (even if empty) for consistency
            result["critical_issues"] = critical_issues
            return result

        except Exception as e:
            self.logger.error(f"Error analyzing token {token_address} with Rugcheck: {str(e)}")
            # Return an error structure, still trying to include raw data if available
            return {
                "rugcheck_passed": False,
                "reason": "analysis_error",
                "error": str(e),
                "rugcheck_score": None,
                "rugcheck_data": score_data if 'score_data' in locals() else None # Include raw data if fetched
            }
        
    async def filter_tokens(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter tokens based on Rugcheck analysis.
        
        Args:
            tokens: List of tokens to filter
            
        Returns:
            List of tokens that passed the Rugcheck filter
        """
        if not tokens:
            self.logger.warning("No tokens provided for Rugcheck filtering")
            return []
            
        filtered_tokens = []
        
        for token in tokens:
            try:
                # Get Rugcheck analysis for the token
                analysis = await self.analyze_token(token)
                
                # Add analysis to token data for reference
                token['rugcheck_analysis'] = analysis
                
                # Only keep tokens that pass the filter
                if analysis['rugcheck_passed']:
                    filtered_tokens.append(token)
                    
            except Exception as e:
                self.logger.error(f"Error processing token {token.get('symbol', 'UNKNOWN')}: {e}")
                continue
                
        self.logger.info(f"Rugcheck filtering complete: {len(filtered_tokens)}/{len(tokens)} tokens passed")
        return filtered_tokens
        
    async def analyze_and_annotate(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyze tokens and annotate them with Rugcheck analysis without filtering.
        
        Args:
            tokens: List of tokens to analyze
            
        Returns:
            The same list of tokens with added Rugcheck analysis data
        """
        if not tokens:
            self.logger.warning("No tokens provided for Rugcheck analysis")
            return []
            
        for token in tokens:
            try:
                # Get Rugcheck analysis for the token
                analysis = await self.analyze_token(token)
                
                # Add analysis to token data
                token['rugcheck_analysis'] = analysis
                    
            except Exception as e:
                self.logger.error(f"Error analyzing token {token.get('symbol', 'UNKNOWN')}: {e}")
                # Ensure error structure matches the format from analyze_token
                token['rugcheck_analysis'] = {
                    "rugcheck_passed": False,
                    "reason": "analysis_error",
                    "error": str(e),
                    "rugcheck_score": None,
                    "rugcheck_data": None # No raw data available in this exception case
                }
                
        self.logger.info(f"Rugcheck analysis complete for {len(tokens)} tokens")
        return tokens 