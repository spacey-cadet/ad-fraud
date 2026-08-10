select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

select
    click_id as unique_field,
    count(*) as n_records

from "warehouse"."main"."stg_ad_clicks"
where click_id is not null
group by click_id
having count(*) > 1



      
    ) dbt_internal_test