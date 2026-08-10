select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select tenure_days
from "warehouse"."main"."churn_features"
where tenure_days is null



      
    ) dbt_internal_test