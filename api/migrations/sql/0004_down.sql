ALTER TABLE app_config DROP COLUMN model_quick, DROP COLUMN model_default, DROP COLUMN model_complex, DROP COLUMN model_router,
                       DROP COLUMN models_available, DROP COLUMN models_checked_at;
DELETE FROM model_price WHERE model IN ('claude-fable-5-1','claude-fable-5','claude-opus-5','claude-opus-4-8','claude-opus-4-7','claude-opus-4-6',
                                        'claude-sonnet-5','claude-sonnet-4-6');
