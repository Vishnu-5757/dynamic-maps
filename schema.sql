--
-- Create model Basin
--
CREATE TABLE `monitoring_basin` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `basin_id` varchar(100) NOT NULL UNIQUE, `name` varchar(255) NULL, `metadata` json NULL, `created_at` datetime(6) NOT NULL, `updated_at` datetime(6) NOT NULL);
--
-- Create model DataType
--
CREATE TABLE `monitoring_datatype` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `name` varchar(64) NOT NULL UNIQUE, `description` longtext NULL);
--
-- Create model BasinRelation
--
CREATE TABLE `monitoring_basinrelation` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `relation_type` varchar(64) NOT NULL, `weight` double precision NULL, `from_basin_id` bigint NOT NULL, `to_basin_id` bigint NOT NULL, CONSTRAINT `unique_basin_relation` UNIQUE (`from_basin_id`, `to_basin_id`, `relation_type`));
--
-- Create model Observation
--
CREATE TABLE `monitoring_observation` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `datetime` datetime(6) NOT NULL, `value` numeric(12, 4) NOT NULL, `source` varchar(128) NOT NULL, `created_at` datetime(6) NOT NULL, `updated_at` datetime(6) NOT NULL, `basin_id` bigint NOT NULL, `data_type_id` bigint NOT NULL, CONSTRAINT `unique_observation_per_source_dt` UNIQUE (`basin_id`, `data_type_id`, `datetime`, `source`));
ALTER TABLE `monitoring_basinrelation` ADD CONSTRAINT `monitoring_basinrela_from_basin_id_a0e7b5e0_fk_monitorin` FOREIGN KEY (`from_basin_id`) REFERENCES `monitoring_basin` (`id`);
ALTER TABLE `monitoring_basinrelation` ADD CONSTRAINT `monitoring_basinrela_to_basin_id_b2a56959_fk_monitorin` FOREIGN KEY (`to_basin_id`) REFERENCES `monitoring_basin` (`id`);
ALTER TABLE `monitoring_observation` ADD CONSTRAINT `monitoring_observation_basin_id_f60be8fd_fk_monitoring_basin_id` FOREIGN KEY (`basin_id`) REFERENCES `monitoring_basin` (`id`);
ALTER TABLE `monitoring_observation` ADD CONSTRAINT `monitoring_observati_data_type_id_b71445f3_fk_monitorin` FOREIGN KEY (`data_type_id`) REFERENCES `monitoring_datatype` (`id`);
CREATE INDEX `idx_basin_dt_type` ON `monitoring_observation` (`basin_id`, `data_type_id`, `datetime`);
CREATE INDEX `idx_type_datetime` ON `monitoring_observation` (`data_type_id`, `datetime`);
CREATE INDEX `idx_datetime` ON `monitoring_observation` (`datetime`);
