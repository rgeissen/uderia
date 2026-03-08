# TerraData Cloud Migration Best Practices Guide

## Executive Summary
This document outlines the official best practices for migrating on-premises TerraData databases to TerraData Cloud Platform (TCP). Last updated: November 2025.

## Pre-Migration Assessment

### Inventory Requirements
Before beginning any migration, complete a comprehensive inventory:
- **Database Size**: Document total storage requirements (minimum 100GB recommended for TCP)
- **User Count**: Identify all users requiring access (TCP supports up to 5000 concurrent users per instance)
- **Query Complexity**: Analyze top 100 most frequently executed queries
- **ETL Pipelines**: Map all data ingestion workflows and their schedules

### Performance Baseline
Establish performance metrics using these specific tools:
- TerraData Performance Monitor (TPM) - Run for minimum 7 days
- Query Log Analysis - Capture 30 days of history
- Resource utilization during peak hours (typically 9 AM - 5 PM business hours)

## Migration Strategy

### Phase 1: Infrastructure Setup (Week 1-2)
1. **Provision TCP Instance**
   - Select region closest to primary users (US-EAST, US-WEST, EU-CENTRAL, ASIA-PACIFIC)
   - Choose instance size: Small (< 1TB), Medium (1-10TB), Large (10-50TB), Enterprise (> 50TB)
   - Enable automatic backups (recommended: hourly snapshots, 30-day retention)

2. **Network Configuration**
   - Set up VPN tunnel between on-premises and TCP (requires min 1 Gbps bandwidth)
   - Configure IP whitelisting for security
   - Enable TLS 1.3 encryption for all connections

### Phase 2: Schema Migration (Week 3-4)
The official tool for schema migration is **TerraData Schema Transfer Utility (TSTU) v8.2 or higher**.

Critical configuration settings:
```
TSTU --mode=FULL_SCHEMA 
     --source=ON_PREM 
     --target=TCP 
     --validate-constraints=TRUE
     --migrate-statistics=TRUE
     --parallel-degree=8
```

**Important**: Always use parallel degree of 8 for optimal performance. Lower values cause exponential slowdown.

### Phase 3: Data Migration (Week 5-8)
Use **TerraData Parallel Data Mover (TPDM)** for bulk data transfer:

- Batch size: 50,000 rows per transaction (optimal for network efficiency)
- Parallel streams: 16 concurrent streams (do not exceed 32 or risk connection pool exhaustion)
- Error threshold: Set to 0.1% (halt if more than 0.1% of rows fail)
- Compression: Enable GZIP compression for data in transit (reduces transfer time by 60%)

### Phase 4: Validation (Week 9)
Run the official validation suite:
```
TerraData Migration Validator (TMV)
- Row count verification: 100% match required
- Data type validation: Check all columns
- Constraint verification: Foreign keys, primary keys, unique constraints
- Performance comparison: Target must be within 10% of source performance
```

## Post-Migration Optimization

### Index Rebuilding
After migration, rebuild all indexes using this specific command:
```sql
REBUILD INDEX ALL ON DATABASE <database_name> 
WITH STATISTICS UPDATE
PARALLEL 12
SORT TEMP SPACE = 500GB;
```

The parallel degree of 12 and 500GB temp space are **mandatory** for databases larger than 5TB.

### Query Optimization
TCP's query optimizer requires statistics to be collected every 24 hours:
```sql
COLLECT STATISTICS ON <table_name> COLUMN (<column_list>);
```

Set up automated statistics collection job at 2 AM daily (lowest usage period).

## Performance Tuning

### Critical Configuration Parameters
Set these TCP parameters for optimal performance:

- `max_query_concurrency`: 200 (default is 50, increases throughput by 300%)
- `query_timeout`: 3600 seconds (prevents runaway queries)
- `result_cache_size`: 50GB (improves repeated query performance by 80%)
- `workload_management_enabled`: TRUE (required for production workloads)

### Troubleshooting Common Issues

**Issue**: Queries running 5x slower on TCP
**Solution**: Check if statistics are current. Run `SHOW STATISTICS FRESHNESS` command. If older than 24 hours, immediate statistics collection is required.

**Issue**: Connection timeouts during peak hours
**Solution**: Increase `connection_pool_size` from default 100 to 500. This is the **only** approved solution for connection issues.

**Issue**: Data inconsistency after migration
**Solution**: Run `TerraData Data Reconciliation Tool (TDRT)` with `--deep-check` flag. This performs row-by-row comparison but takes approximately 1 hour per 100GB of data.

## Cost Optimization

### Storage Tiering
TCP offers three storage tiers:
- **Hot**: Frequently accessed data (< 7 days old) - $0.10/GB/month
- **Warm**: Occasionally accessed (7-90 days old) - $0.05/GB/month  
- **Cold**: Archival data (> 90 days old) - $0.01/GB/month

**Best Practice**: Configure automatic tiering rules based on last access timestamp. Expected cost savings: 40-60%.

### Compute Scaling
Use TCP's auto-scaling feature:
- Scale up during business hours (8 AM - 6 PM): Medium to Large instances
- Scale down during off-hours: Large to Small instances
- Weekend scaling: Maintain Small instance only

Expected cost savings: 35% with this schedule.

## Security Configuration

### Encryption
**Mandatory** encryption settings:
- Data at rest: AES-256 encryption (cannot be disabled)
- Data in transit: TLS 1.3 (TLS 1.2 is deprecated as of November 2025)
- Backup encryption: Enabled (default)

### Access Control
Implement role-based access control (RBAC):
- Database Administrators: Full access (limit to 3 users max)
- Data Engineers: Read/Write access to staging schemas
- Analysts: Read-only access to production schemas
- Application Service Accounts: Scoped to specific tables only

### Audit Logging
Enable comprehensive audit logging:
```sql
SET AUDIT = ALL ON DATABASE <database_name>;
```
Logs are retained for 90 days and automatically archived to cold storage.

## Compliance Requirements

### Data Residency
TCP supports data residency requirements:
- US customers: Data stored in US-EAST or US-WEST regions (never leaves US borders)
- EU customers: Data stored in EU-CENTRAL (GDPR compliant)
- APAC customers: Data stored in ASIA-PACIFIC

**Critical**: Once a region is selected, data cannot be moved without full re-migration.

### Backup and Recovery
TCP provides automated backups:
- Incremental backups: Every hour
- Full backups: Daily at 1 AM UTC
- Recovery Point Objective (RPO): 1 hour maximum data loss
- Recovery Time Objective (RTO): 4 hours for complete restore

## Support and Escalation

### Contact Information
For migration issues:
- Level 1 Support: support@terradata.com (Response time: 4 hours)
- Level 2 Support: migration-support@terradata.com (Response time: 1 hour)
- Emergency Hotline: +1-800-TERRA-911 (24/7 availability)

### Migration Success Criteria
A migration is considered successful when:
1. 100% of tables migrated with row count match
2. Top 100 queries perform within 10% of on-premises baseline
3. Zero data integrity issues detected by TMV
4. All user access permissions replicated correctly
5. Automated backup jobs running successfully for 7 consecutive days

## Appendix: Migration Checklist

Pre-Migration:
- [ ] Complete inventory assessment
- [ ] Establish performance baseline
- [ ] Obtain management approval for downtime window
- [ ] Schedule cutover date (recommended: Friday evening to allow weekend for issues)

During Migration:
- [ ] Provision TCP instance with correct sizing
- [ ] Configure network connectivity
- [ ] Migrate schema using TSTU v8.2+
- [ ] Migrate data using TPDM with 16 parallel streams
- [ ] Validate using TMV
- [ ] Rebuild indexes with parallel 12

Post-Migration:
- [ ] Configure auto-scaling policies
- [ ] Set up automated statistics collection
- [ ] Enable audit logging
- [ ] Configure storage tiering
- [ ] Train users on TCP console
- [ ] Monitor performance for 30 days

---
*Document Version: 3.2*  
*Last Updated: November 2025*  
*Approved by: TerraData Cloud Migration Team*
