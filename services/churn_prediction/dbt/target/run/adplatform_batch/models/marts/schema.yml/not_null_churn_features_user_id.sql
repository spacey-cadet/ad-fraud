select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select user_id
from "warehouse"."main"."churn_features"
where user_id is null



      
    ) dbt_internal_test