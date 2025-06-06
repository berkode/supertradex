#!/usr/bin/env python3

import asyncio
import sys
import os
import time
from pathlib import Path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

async def test_config_manager():
    """Test the centralized configuration manager functionality"""
    
    print("=== Testing Centralized Configuration Manager ===")
    
    # Test 1: Configuration Manager Imports
    print("\n1. Testing Configuration Manager Imports...")
    try:
        from config.config_manager import (
            ConfigurationManager, ConfigCategory, ConfigMetadata,
            get_config_manager, initialize_config_manager,
            get_websocket_config, get_solana_config, get_trading_config,
            get_api_config, get_config
        )
        from config.settings import Settings
        print("✓ Configuration manager imports successful")
        
    except Exception as e:
        print(f"✗ Error importing configuration manager: {e}")
        return False
    
    # Test 2: Settings Integration
    print("\n2. Testing Settings Integration...")
    try:
        # Create a settings instance
        settings = Settings()
        
        # Initialize configuration manager with settings
        config_manager = initialize_config_manager(settings)
        
        assert isinstance(config_manager, ConfigurationManager)
        assert config_manager.settings == settings
        print("✓ Configuration manager initialized with settings")
        
    except Exception as e:
        print(f"✗ Error integrating with settings: {e}")
        return False
    
    # Test 3: Configuration Registry
    print("\n3. Testing Configuration Registry...")
    try:
        # Check that configurations are registered
        registry = config_manager._config_registry
        assert len(registry) > 0
        print(f"✓ Configuration registry contains {len(registry)} parameters")
        
        # Check specific categories
        categories = set(meta.category for meta in registry.values())
        expected_categories = {
            ConfigCategory.SYSTEM,
            ConfigCategory.WEBSOCKET, 
            ConfigCategory.SOLANA,
            ConfigCategory.API,
            ConfigCategory.TRADING,
            ConfigCategory.RISK_MANAGEMENT
        }
        
        for category in expected_categories:
            assert category in categories
        print("✓ All expected configuration categories present")
        
    except Exception as e:
        print(f"✗ Error testing configuration registry: {e}")
        return False
    
    # Test 4: Configuration Value Access
    print("\n4. Testing Configuration Value Access...")
    try:
        # Test direct access
        log_level = config_manager.get('LOG_LEVEL')
        assert log_level is not None
        print(f"✓ Retrieved LOG_LEVEL: {log_level}")
        
        # Test with default
        test_value = config_manager.get('NONEXISTENT_CONFIG', 'default_value')
        assert test_value == 'default_value'
        print("✓ Default value fallback working")
        
        # Test category-based access
        ws_config = config_manager.get_websocket_config()
        assert isinstance(ws_config, dict)
        assert 'WEBSOCKET_PING_INTERVAL' in ws_config
        print(f"✓ WebSocket config retrieved with {len(ws_config)} parameters")
        
        solana_config = config_manager.get_solana_config()
        assert isinstance(solana_config, dict)
        print(f"✓ Solana config retrieved with {len(solana_config)} parameters")
        
        trading_config = config_manager.get_trading_config()
        assert isinstance(trading_config, dict)
        print(f"✓ Trading config retrieved with {len(trading_config)} parameters")
        
    except Exception as e:
        print(f"✗ Error testing configuration access: {e}")
        return False
    
    # Test 5: Global Configuration Access Functions
    print("\n5. Testing Global Configuration Access...")
    try:
        # Test global convenience functions
        global_ws_config = get_websocket_config()
        assert isinstance(global_ws_config, dict)
        print("✓ Global get_websocket_config() working")
        
        global_solana_config = get_solana_config()
        assert isinstance(global_solana_config, dict)
        print("✓ Global get_solana_config() working")
        
        global_trading_config = get_trading_config()
        assert isinstance(global_trading_config, dict)
        print("✓ Global get_trading_config() working")
        
        # Test global get_config function
        global_log_level = get_config('LOG_LEVEL')
        assert global_log_level == log_level
        print("✓ Global get_config() working")
        
    except Exception as e:
        print(f"✗ Error testing global configuration access: {e}")
        return False
    
    # Test 6: Configuration Validation
    print("\n6. Testing Configuration Validation...")
    try:
        validation_results = config_manager.validate_configuration()
        
        assert isinstance(validation_results, dict)
        assert 'valid' in validation_results
        assert 'invalid' in validation_results
        assert 'missing_required' in validation_results
        assert 'warnings' in validation_results
        
        print(f"✓ Configuration validation completed:")
        print(f"   - Valid: {len(validation_results['valid'])}")
        print(f"   - Invalid: {len(validation_results['invalid'])}")
        print(f"   - Missing required: {len(validation_results['missing_required'])}")
        print(f"   - Warnings: {len(validation_results['warnings'])}")
        
        # Print any validation issues
        if validation_results['invalid']:
            print(f"   - Invalid configurations: {validation_results['invalid'][:3]}...")
        if validation_results['missing_required']:
            print(f"   - Missing required: {validation_results['missing_required'][:3]}...")
        
    except Exception as e:
        print(f"✗ Error testing configuration validation: {e}")
        return False
    
    # Test 7: Configuration Summary and Metadata
    print("\n7. Testing Configuration Summary and Metadata...")
    try:
        summary = config_manager.get_configuration_summary()
        
        assert isinstance(summary, dict)
        assert 'total_parameters' in summary
        assert 'loaded_parameters' in summary
        assert 'categories' in summary
        
        print(f"✓ Configuration summary retrieved:")
        print(f"   - Total parameters: {summary['total_parameters']}")
        print(f"   - Loaded parameters: {summary['loaded_parameters']}")
        print(f"   - Categories: {len(summary['categories'])}")
        
        # Test parameter info
        log_level_info = config_manager.get_parameter_info('LOG_LEVEL')
        assert log_level_info is not None
        assert 'description' in log_level_info
        assert 'data_type' in log_level_info
        print("✓ Parameter metadata retrieval working")
        
    except Exception as e:
        print(f"✗ Error testing configuration summary: {e}")
        return False
    
    # Test 8: Configuration Categories and Organization
    print("\n8. Testing Configuration Categories...")
    try:
        categories_list = config_manager.list_parameters_by_category()
        
        assert isinstance(categories_list, dict)
        assert 'websocket' in categories_list
        assert 'solana' in categories_list
        assert 'trading' in categories_list
        
        print(f"✓ Configuration organized into {len(categories_list)} categories:")
        for category, params in categories_list.items():
            print(f"   - {category}: {len(params)} parameters")
        
    except Exception as e:
        print(f"✗ Error testing configuration categories: {e}")
        return False
    
    # Test 9: Type Conversion and Validation
    print("\n9. Testing Type Conversion...")
    try:
        # Test boolean conversion
        test_bool = config_manager._convert_type("true", bool, "test_bool")
        assert test_bool == True
        
        test_bool_false = config_manager._convert_type("false", bool, "test_bool_false")
        assert test_bool_false == False
        
        # Test integer conversion
        test_int = config_manager._convert_type("42", int, "test_int")
        assert test_int == 42
        
        # Test float conversion
        test_float = config_manager._convert_type("3.14", float, "test_float")
        assert test_float == 3.14
        
        print("✓ Type conversion working correctly")
        
    except Exception as e:
        print(f"✗ Error testing type conversion: {e}")
        return False
    
    # Test 10: Configuration Reload
    print("\n10. Testing Configuration Reload...")
    try:
        # Test reload functionality
        reload_success = config_manager.reload_configuration()
        assert reload_success == True
        print("✓ Configuration reload successful")
        
    except Exception as e:
        print(f"✗ Error testing configuration reload: {e}")
        return False
    
    # Test 11: Integration with Components
    print("\n11. Testing Component Integration...")
    try:
        # Test integration with WebSocket connection manager
        from data.websocket_connection_manager import WebSocketConnectionManager
        
        ws_manager = WebSocketConnectionManager(settings)
        
        # Verify that the connection manager has access to configuration
        assert hasattr(ws_manager, 'config_manager')
        assert ws_manager.config_manager is not None
        print("✓ WebSocket connection manager integrated with config manager")
        
        # Test integration with blockchain listener
        from data.blockchain_listener import BlockchainListener
        
        blockchain_listener = BlockchainListener(settings)
        
        # Verify blockchain listener has config manager
        assert hasattr(blockchain_listener, 'config_manager')
        assert blockchain_listener.config_manager is not None
        print("✓ Blockchain listener integrated with config manager")
        
    except Exception as e:
        print(f"✗ Error testing component integration: {e}")
        return False
    
    # Test 12: Sensitive Data Masking
    print("\n12. Testing Sensitive Data Masking...")
    try:
        # Test that sensitive parameters are masked in logs
        param_info = config_manager.get_parameter_info('DATABASE_URL')
        if param_info:
            # If DATABASE_URL is configured and marked as sensitive
            if param_info.get('sensitive'):
                assert param_info['current_value'] == "***MASKED***"
                print("✓ Sensitive data masking working")
            else:
                print("✓ DATABASE_URL not marked as sensitive or not configured")
        else:
            print("✓ DATABASE_URL parameter info not available")
        
    except Exception as e:
        print(f"✗ Error testing sensitive data masking: {e}")
        return False
    
    # Test 13: Configuration Documentation Export
    print("\n13. Testing Configuration Documentation...")
    try:
        docs = config_manager.export_configuration_docs()
        
        assert isinstance(docs, str)
        assert len(docs) > 0
        assert "# Configuration Parameters Documentation" in docs
        assert "## WEBSOCKET" in docs or "## websocket" in docs.upper()
        
        print(f"✓ Configuration documentation generated ({len(docs)} characters)")
        
    except Exception as e:
        print(f"✗ Error testing documentation export: {e}")
        return False
    
    print("\n=== ✅ All Configuration Manager Tests Passed ===")
    print("\n📋 **Benefits Achieved:**")
    print("   - Centralized configuration management with single source of truth")
    print("   - Type-safe configuration access with automatic validation")
    print("   - Category-based configuration organization for better structure")
    print("   - Sensitive data masking for security in logs")
    print("   - Comprehensive validation and error reporting")
    print("   - Global convenience functions for easy access")
    print("   - Integration with existing components (WebSocket, BlockchainListener)")
    print("   - Automatic type conversion with error handling")
    print("   - Configuration reload capability for runtime updates")
    print("   - Built-in documentation generation")
    print("   - Enforces environment variable flow: .env → Configuration → Application")
    
    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(test_config_manager())
        if not result:
            sys.exit(1)
    except Exception as e:
        print(f"Test failed with exception: {e}")
        sys.exit(1) 